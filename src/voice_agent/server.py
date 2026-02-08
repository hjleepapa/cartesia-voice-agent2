import asyncio
import json
import logging
import os
import threading
import traceback
import uuid
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List
import time

from flask import Blueprint, Flask, jsonify, redirect, render_template, request, send_from_directory, url_for, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRecorder
import httpx

from .agents import MortgageAgent
from .config import settings
from .memory import MemoryStore
from .stt_cartesia import CartesiaSTTClient
from .tts_cartesia import CartesiaTTSClient


# Ensure project root is on sys.path so convonet imports work
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_agent_state: Dict[str, Any] = {
    "logged_in": False,
    "agent": None,
    "status": "logged-out",
    "last_call": None,
}

logger = logging.getLogger(__name__)

_pcs = set()
_pc_state: Dict[RTCPeerConnection, Dict[str, Any]] = {}
_loop = asyncio.new_event_loop()
_loop_thread: Optional[threading.Thread] = None

_interactions: List[Dict[str, Any]] = []
_browser_session_cache: Dict[str, Any] = {"url": None, "created_at": 0.0}
_db_engine = None
_db_sessionmaker = None


def _start_loop() -> None:
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


def _run_coro(coro: asyncio.Future) -> Any:
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


def _assets_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "convonet_assets"


def _call_center_dirs() -> Dict[str, Path]:
    base = _assets_dir() / "call_center"
    return {"templates": base / "templates", "static": base / "static"}


def _get_db_session():
    global _db_engine, _db_sessionmaker
    if _db_sessionmaker is None:
        db_uri = os.getenv("DB_URI") or settings.memory_db_uri
        if not db_uri:
            raise RuntimeError("DB_URI is required for mortgage dashboard.")
        _db_engine = create_engine(db_uri, pool_pre_ping=True)
        _db_sessionmaker = sessionmaker(bind=_db_engine)
        try:
            from convonet.models.base import Base
            from convonet.models import mortgage_models  # noqa: F401
            Base.metadata.create_all(bind=_db_engine)
        except Exception:
            logger.exception("Failed to initialize mortgage tables.")
    return _db_sessionmaker()


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _serialize_application(app, include_details: bool = False) -> Dict[str, Any]:
    documents = list(app.documents or [])
    debts = list(app.debts or [])
    payload = {
        "application_id": str(app.id),
        "user_id": str(app.user_id),
        "status": _enum_value(app.status),
        "credit_score": app.credit_score,
        "dti_ratio": float(app.dti_ratio) if app.dti_ratio is not None else None,
        "monthly_income": float(app.monthly_income) if app.monthly_income is not None else None,
        "monthly_debt": float(app.monthly_debt) if app.monthly_debt is not None else None,
        "down_payment_amount": float(app.down_payment_amount) if app.down_payment_amount is not None else None,
        "total_savings": float(app.total_savings) if app.total_savings is not None else None,
        "completion_percentage": app.get_completion_percentage(),
        "documents_count": len(documents),
        "debts_count": len(debts),
        "created_at": app.created_at.isoformat() if app.created_at else None,
    }
    if include_details:
        payload["documents"] = [
            {
                "document_name": doc.document_name,
                "document_type": _enum_value(doc.document_type),
                "status": _enum_value(doc.status),
            }
            for doc in documents
        ]
        payload["debts"] = [
            {
                "debt_type": debt.debt_type,
                "monthly_payment": float(debt.monthly_payment),
                "outstanding_balance": float(debt.outstanding_balance) if debt.outstanding_balance else None,
            }
            for debt in debts
        ]
    return payload


def _twilio_transfer_twiml(extension: str) -> str:
    sip_domain = os.getenv("TWILIO_SIP_DOMAIN") or os.getenv("SIP_DOMAIN") or "sip.example.com"
    sip_target = f"sip:{extension}@{sip_domain}"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>
    <Sip>{sip_target}</Sip>
  </Dial>
</Response>
"""


def _build_customer_payload(customer_id: Optional[str]) -> Dict[str, Any]:
    memory = MemoryStore(settings.memory_db_uri)
    recent = memory.recent(limit=6)
    conversation_history = [{"role": role, "content": content} for role, content in recent]

    return {
        "customer_id": customer_id or "CUST-001",
        "name": "Alex Kim",
        "email": "alex.kim@example.com",
        "phone": "+1 (415) 555-0134",
        "account_status": "Active",
        "tier": "Gold",
        "last_contact": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "open_tickets": 1,
        "lifetime_value": "$32,400",
        "notes": "Interested in 30-year fixed mortgage options.",
        "conversation_history": conversation_history,
        "activities": [
            {
                "activity_type": "mortgage",
                "title": "Mortgage pre-qualification",
                "result": "DTI calculated at 33%.",
            },
            {
                "activity_type": "todo",
                "title": "Document checklist",
                "result": "Awaiting pay stubs and W-2s.",
            },
        ],
    }


async def _assistant_response_async(text: str) -> Dict[str, Any]:
    start_time = time.monotonic()
    tool_log: List[Dict[str, Any]] = []
    memory = MemoryStore(settings.memory_db_uri)
    agent = MortgageAgent(memory=memory, tool_log=tool_log)
    response_text = await agent.run(text)
    audio_name = f"assistant_{uuid.uuid4().hex}.wav"
    audio_dir = _assets_dir() / "generated_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / audio_name
    CartesiaTTSClient().synthesize_to_file(response_text, str(audio_path))
    duration_ms = int((time.monotonic() - start_time) * 1000)
    search_results: List[Dict[str, Any]] = []
    for entry in tool_log:
        if entry.get("tool_name") == "search_web" and entry.get("results"):
            search_results = entry["results"]
            break

    live_url: Optional[str] = None
    if search_results:
        live_url = await _maybe_create_browser_session(text)

    _interactions.append(
        {
            "request_id": uuid.uuid4().hex,
            "datetime": datetime.utcnow().isoformat(),
            "provider": "claude",
            "model": settings.anthropic_model,
            "status": "success",
            "user_prompt": text,
            "agent_response": response_text,
            "tool_calls": tool_log,
            "duration_ms": duration_ms,
            "metadata": {"agent_type": "mortgage"},
        }
    )
    return {
        "success": True,
        "text": response_text,
        "search_results": search_results,
        "live_url": live_url,
        "audio_url": f"/call-center/generated-audio/{audio_name}",
    }


def _assistant_response(text: str) -> Dict[str, Any]:
    return asyncio.run(_assistant_response_async(text))


async def _process_audio_file(path: Path) -> Dict[str, Any]:
    stt_client = CartesiaSTTClient()
    text = await asyncio.to_thread(stt_client.transcribe_file, str(path))
    if not text:
        return {"success": False, "error": "Transcription failed."}
    response = await _assistant_response_async(text)
    response["user_text"] = text
    return response


async def _maybe_create_browser_session(query: str) -> Optional[str]:
    api_key = os.getenv("BROWSERBASE_API_KEY")
    project_id = os.getenv("BROWSERBASE_PROJECT_ID")
    if not api_key or not project_id:
        logger.info("Browserbase disabled: missing API key or project id.")
        return None
    ttl_seconds = int(os.getenv("BROWSERBASE_SESSION_TTL", "180"))
    now = time.monotonic()
    cached_url = _browser_session_cache.get("url")
    cached_at = _browser_session_cache.get("created_at", 0.0)
    if cached_url and (now - cached_at) < ttl_seconds:
        logger.info("Browserbase using cached session URL.")
        return cached_url
    # Google often blocks automated/embedded sessions; use DuckDuckGo for reliability.
    search_url = f"https://duckduckgo.com/?q={httpx.QueryParams({'q': query})['q']}"
    headers = {"X-BB-API-Key": api_key, "Content-Type": "application/json"}
    payload = {
        "projectId": project_id,
        "keepAlive": True,
        "browserSettings": {"startUrl": search_url},
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        logger.info("Browserbase creating session (project=%s)", project_id)
        create_resp = await client.post(
            "https://api.browserbase.com/v1/sessions",
            headers=headers,
            json=payload,
        )
        create_resp.raise_for_status()
        session_payload = create_resp.json()
        session_id = session_payload.get("id")
        if not session_id:
            logger.error("Browserbase session create returned no id: %s", session_payload)
            return None
        logger.info("Browserbase session created: %s", session_id)
        try:
            live_resp = await client.get(
                f"https://api.browserbase.com/v1/sessions/{session_id}/live-urls",
                headers=headers,
            )
            live_resp.raise_for_status()
            data = live_resp.json()
            live_url = data.get("liveUrl") or data.get("live_url")
            if live_url:
                _browser_session_cache["url"] = live_url
                _browser_session_cache["created_at"] = now
                logger.info("Browserbase live URL ready.")
            return live_url
        except httpx.HTTPStatusError:
            # Fallbacks when live-urls isn't available on plan or not ready
            connect_url = session_payload.get("connectUrl") or session_payload.get("connect_url")
            if connect_url:
                _browser_session_cache["url"] = connect_url
                _browser_session_cache["created_at"] = now
                logger.info("Browserbase using connect URL fallback.")
                return connect_url
            session_page = f"https://www.browserbase.com/sessions/{session_id}"
            _browser_session_cache["url"] = session_page
            _browser_session_cache["created_at"] = now
            logger.info("Browserbase using session page fallback.")
            return session_page


async def _handle_offer(offer_sdp: str, offer_type: str) -> Dict[str, str]:
    pc = RTCPeerConnection()
    _pcs.add(pc)
    _pc_state[pc] = {"track": None, "recorder": None, "audio_path": None}

    @pc.on("track")
    def on_track(track) -> None:
        if track.kind == "audio":
            _pc_state[pc]["track"] = track

    @pc.on("datachannel")
    def on_datachannel(channel) -> None:
        async def _start_recording() -> None:
            track = _pc_state[pc].get("track")
            if not track:
                channel.send(json.dumps({"type": "error", "error": "No audio track available."}))
                return
            temp_dir = _assets_dir() / "temp_audio"
            temp_dir.mkdir(parents=True, exist_ok=True)
            path = temp_dir / f"webrtc_{uuid.uuid4().hex}.wav"
            recorder = MediaRecorder(str(path))
            recorder.addTrack(track)
            _pc_state[pc]["recorder"] = recorder
            _pc_state[pc]["audio_path"] = path
            await recorder.start()
            channel.send(json.dumps({"type": "status", "status": "recording"}))

        async def _stop_recording() -> None:
            recorder = _pc_state[pc].get("recorder")
            path = _pc_state[pc].get("audio_path")
            if recorder:
                await recorder.stop()
            if not path:
                channel.send(json.dumps({"type": "error", "error": "No audio recorded."}))
                return
            channel.send(json.dumps({"type": "status", "status": "transcribing"}))
            try:
                result = await _process_audio_file(path)
                if result.get("success"):
                    payload = {
                        "type": "assistant_response",
                        "text": result.get("text", ""),
                        "user_text": result.get("user_text", ""),
                        "audio_url": result.get("audio_url", ""),
                    }
                else:
                    payload = {"type": "error", "error": result.get("error", "Failed.")}
                channel.send(json.dumps(payload))
            except Exception as exc:
                logger.error("WebRTC processing failed: %s", exc)
                logger.error("WebRTC traceback:\n%s", traceback.format_exc())
                channel.send(
                    json.dumps(
                        {
                            "type": "error",
                            "error": f"Assistant error: {exc}",
                        }
                    )
                )
            finally:
                try:
                    path.unlink()
                except OSError:
                    pass

        @channel.on("message")
        def on_message(message: Any) -> None:
            if message == "start":
                asyncio.create_task(_start_recording())
            elif message == "stop":
                asyncio.create_task(_stop_recording())

    await pc.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type=offer_type))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}


def create_app() -> Flask:
    global _loop_thread
    if _loop_thread is None:
        _loop_thread = threading.Thread(target=_start_loop, daemon=True)
        _loop_thread.start()

    app = Flask(__name__, template_folder=str(_assets_dir() / "templates"))
    dirs = _call_center_dirs()

    call_center = Blueprint(
        "call_center",
        __name__,
        static_folder=str(dirs["static"]),
        template_folder=str(dirs["templates"]),
        url_prefix="/call-center",
    )

    @call_center.route("/", methods=["GET"])
    def call_center_home() -> str:
        sip_config = {
            "domain": os.getenv("SIP_DOMAIN", "sip.example.com"),
            "wss_port": int(os.getenv("SIP_WSS_PORT", "7443")),
            "transfer_extension": os.getenv("HUMAN_TRANSFER_EXTENSION", "2001"),
        }
        return render_template("call_center.html", sip_config=sip_config)

    @call_center.route("/api/agent/login", methods=["POST"])
    def agent_login() -> Any:
        payload = request.get_json(silent=True) or {}
        agent = {
            "agent_id": payload.get("agent_id", "agent-001"),
            "name": payload.get("name", "Agent"),
            "sip_username": payload.get("sip_username", "demo-agent"),
            "sip_domain": payload.get("sip_domain", "sip.example.com"),
            "sip_extension": payload.get("sip_extension") or payload.get("agent_id") or "1001",
        }
        _agent_state.update(
            {"logged_in": True, "agent": agent, "status": "logged-in"}
        )
        return jsonify({"success": True, "agent": agent})

    @call_center.route("/api/agent/logout", methods=["POST"])
    def agent_logout() -> Any:
        _agent_state.update({"logged_in": False, "agent": None, "status": "logged-out"})
        return jsonify({"success": True})

    @call_center.route("/api/agent/ready", methods=["POST"])
    def agent_ready() -> Any:
        _agent_state["status"] = "ready"
        return jsonify({"success": True})

    @call_center.route("/api/agent/not-ready", methods=["POST"])
    def agent_not_ready() -> Any:
        payload = request.get_json(silent=True) or {}
        _agent_state["status"] = "not-ready"
        _agent_state["reason"] = payload.get("reason")
        return jsonify({"success": True})

    @call_center.route("/api/agent/status", methods=["GET"])
    def agent_status() -> Any:
        return jsonify(
            {
                "logged_in": _agent_state["logged_in"],
                "agent": _agent_state.get("agent"),
                "status": _agent_state.get("status"),
            }
        )

    @call_center.route("/api/call/ringing", methods=["POST"])
    def call_ringing() -> Any:
        _agent_state["last_call"] = request.get_json(silent=True) or {}
        return jsonify({"success": True})

    @call_center.route("/api/call/answer", methods=["POST"])
    def call_answer() -> Any:
        return jsonify({"success": True})

    @call_center.route("/api/call/drop", methods=["POST"])
    def call_drop() -> Any:
        return jsonify({"success": True})

    @call_center.route("/api/call/hold", methods=["POST"])
    def call_hold() -> Any:
        return jsonify({"success": True})

    @call_center.route("/api/call/unhold", methods=["POST"])
    def call_unhold() -> Any:
        return jsonify({"success": True})

    @call_center.route("/api/call/transfer", methods=["POST"])
    def call_transfer() -> Any:
        return jsonify({"success": True})

    @call_center.route("/api/customer/data", methods=["GET"])
    def customer_data() -> Any:
        customer_id = request.args.get("customer_id")
        return jsonify(_build_customer_payload(customer_id))

    @call_center.route("/api/assistant/respond", methods=["POST"])
    def assistant_respond() -> Any:
        payload = request.get_json(silent=True) or {}
        text = payload.get("text", "")
        if not text:
            return jsonify({"success": False, "error": "text is required"}), 400
        return jsonify(_assistant_response(text))

    @call_center.route("/generated-audio/<path:filename>", methods=["GET"])
    def generated_audio(filename: str) -> Any:
        audio_dir = _assets_dir() / "generated_audio"
        return send_from_directory(audio_dir, filename)

    app.register_blueprint(call_center)

    @app.route("/webrtc/voice-assistant", methods=["GET"])
    def webrtc_voice_assistant() -> Any:
        return render_template("voice_assistant.html")

    @app.route("/convonet_todo/Mortgage/dashboard", methods=["GET"])
    def mortgage_dashboard() -> Any:
        return render_template("mortgage_dashboard.html")

    @app.route("/convonet_todo/twilio/transfer", methods=["GET", "POST"])
    def twilio_transfer() -> Any:
        extension = (
            request.args.get("extension")
            or request.form.get("extension")
            or os.getenv("HUMAN_TRANSFER_EXTENSION", "2001")
        )
        logger.info(
            "Twilio transfer requested (endpoint=/convonet_todo/twilio/transfer, extension=%s, remote=%s)",
            extension,
            request.remote_addr,
        )
        twiml = _twilio_transfer_twiml(extension)
        return Response(twiml, mimetype="text/xml")

    @app.route("/convonet_todo/twilio/voice_assistant/transfer_bridge", methods=["GET", "POST"])
    def twilio_transfer_bridge() -> Any:
        extension = (
            request.args.get("extension")
            or request.form.get("extension")
            or os.getenv("HUMAN_TRANSFER_EXTENSION", "2001")
        )
        logger.info(
            "Twilio transfer requested (endpoint=/convonet_todo/twilio/voice_assistant/transfer_bridge, extension=%s, remote=%s)",
            extension,
            request.remote_addr,
        )
        twiml = _twilio_transfer_twiml(extension)
        return Response(twiml, mimetype="text/xml")

    @app.route("/convonet_todo/twilio/transfer_callback", methods=["POST"])
    def twilio_transfer_callback() -> Any:
        logger.info(
            "Twilio transfer callback received (remote=%s, form=%s)",
            request.remote_addr,
            dict(request.form),
        )
        return Response("<Response></Response>", mimetype="text/xml")

    @app.route("/convonet_todo/api/mortgage/applications", methods=["GET"])
    def mortgage_applications() -> Any:
        db = None
        try:
            from convonet.models.mortgage_models import MortgageApplication
            db = _get_db_session()
            applications = (
                db.query(MortgageApplication)
                .order_by(MortgageApplication.created_at.desc())
                .all()
            )
            return jsonify(
                {
                    "success": True,
                    "applications": [
                        _serialize_application(app, include_details=False)
                        for app in applications
                    ],
                }
            )
        except Exception as exc:
            logger.exception("Failed to load mortgage applications.")
            return jsonify({"success": False, "error": str(exc)}), 500
        finally:
            try:
                if db is not None:
                    db.close()
            except Exception:
                pass

    @app.route("/convonet_todo/api/mortgage/applications/<application_id>", methods=["GET"])
    def mortgage_application_detail(application_id: str) -> Any:
        db = None
        try:
            from uuid import UUID
            from convonet.models.mortgage_models import MortgageApplication

            db = _get_db_session()
            application = (
                db.query(MortgageApplication)
                .filter(MortgageApplication.id == UUID(application_id))
                .first()
            )
            if not application:
                return jsonify({"success": False, "error": "Application not found"}), 404
            return jsonify(
                {
                    "success": True,
                    "application": _serialize_application(application, include_details=True),
                }
            )
        except Exception as exc:
            logger.exception("Failed to load mortgage application detail.")
            return jsonify({"success": False, "error": str(exc)}), 500
        finally:
            try:
                if db is not None:
                    db.close()
            except Exception:
                pass

    @app.route("/agent-monitor", methods=["GET"])
    def agent_monitor() -> Any:
        return render_template("agent_monitor_dashboard.html")

    @app.route("/api/assistant/respond", methods=["POST"])
    def api_assistant_respond() -> Any:
        payload = request.get_json(silent=True) or {}
        text = payload.get("text", "")
        if not text:
            return jsonify({"success": False, "error": "text is required"}), 400
        return jsonify(_assistant_response(text))

    @app.route("/api/assistant/transcribe", methods=["POST"])
    def api_assistant_transcribe() -> Any:
        if "audio" not in request.files:
            return jsonify({"success": False, "error": "audio file is required"}), 400
        audio_file = request.files["audio"]
        if not audio_file.filename:
            return jsonify({"success": False, "error": "audio file is required"}), 400

        temp_dir = _assets_dir() / "temp_audio"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"mic_{uuid.uuid4().hex}.webm"
        audio_file.save(temp_path)

        try:
            stt_client = CartesiaSTTClient()
            text = asyncio.run(stt_client.transcribe_file(str(temp_path)))
            return jsonify({"success": True, "text": text})
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass

    @app.route("/api/notion/tools", methods=["GET"])
    def notion_tools() -> Any:
        from .mcp_notion import NotionMCPClient

        client = NotionMCPClient()
        try:
            result = _run_coro(client.list_tools())
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/webrtc/offer", methods=["POST"])
    def webrtc_offer() -> Any:
        payload = request.get_json(silent=True) or {}
        sdp = payload.get("sdp")
        type_ = payload.get("type")
        if not sdp or not type_:
            return jsonify({"error": "sdp and type are required"}), 400
        answer = _run_coro(_handle_offer(sdp, type_))
        return jsonify(answer)

    @app.route("/agent-monitor/api/stats", methods=["GET"])
    def agent_monitor_stats() -> Any:
        total = len(_interactions)
        by_provider: Dict[str, int] = {}
        total_tool_calls = 0
        durations = []
        for item in _interactions:
            provider = item.get("provider") or "unknown"
            by_provider[provider] = by_provider.get(provider, 0) + 1
            tool_calls = item.get("tool_calls") or []
            total_tool_calls += len(tool_calls)
            if item.get("duration_ms") is not None:
                durations.append(item["duration_ms"])
        avg_duration = sum(durations) / len(durations) if durations else 0
        return jsonify(
            {
                "success": True,
                "stats": {
                    "total_interactions": total,
                    "by_provider": by_provider,
                    "total_tool_calls": total_tool_calls,
                    "avg_duration_ms": avg_duration,
                },
            }
        )

    @app.route("/agent-monitor/api/interactions", methods=["GET"])
    def agent_monitor_interactions() -> Any:
        limit = int(request.args.get("limit", "50"))
        provider = request.args.get("provider")
        agent_type = request.args.get("agent_type")
        filtered = _interactions
        if provider:
            filtered = [i for i in filtered if i.get("provider") == provider]
        if agent_type:
            filtered = [i for i in filtered if i.get("metadata", {}).get("agent_type") == agent_type]
        return jsonify({"success": True, "interactions": list(reversed(filtered))[:limit]})

    return app


def main() -> None:
    app = create_app()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
