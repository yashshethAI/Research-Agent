from __future__ import annotations

import sys
import uuid
from pathlib import Path

import streamlit as st

# Ensure project root is in sys.path regardless of execution directory
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from frontend.components.evidence_panel import render_evidence_panel
    from frontend.components.sidebar import render_sidebar
    from frontend.services.api_client import api_client
except ModuleNotFoundError:
    from components.evidence_panel import render_evidence_panel
    from components.sidebar import render_sidebar
    from services.api_client import api_client

# Page Configuration
st.set_page_config(
    page_title="GST Practice Copilot – India",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }
    .stAlert {
        border-radius: 8px;
    }
    .memorandum-header {
        font-family: 'Georgia', serif;
        border-bottom: 2px solid #0d47a1;
        padding-bottom: 8px;
        margin-bottom: 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize Session State
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "uploaded_attachment_ids" not in st.session_state:
    st.session_state.uploaded_attachment_ids = []


def refresh_backend_data():
    st.session_state.config_status = api_client.get_config_status()
    st.session_state.conversations = api_client.list_conversations()


if "config_status" not in st.session_state or "conversations" not in st.session_state:
    refresh_backend_data()


# Sidebar Callbacks
def handle_new_chat():
    st.session_state.conversation_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.uploaded_attachment_ids = []
    refresh_backend_data()
    st.rerun()


def handle_select_conv(conv_id: str):
    st.session_state.conversation_id = conv_id
    msgs = api_client.get_conversation(conv_id)
    st.session_state.messages = msgs
    st.session_state.uploaded_attachment_ids = []
    refresh_backend_data()
    st.rerun()


def handle_delete_conv(conv_id: str):
    api_client.delete_conversation(conv_id)
    if st.session_state.conversation_id == conv_id:
        st.session_state.conversation_id = str(uuid.uuid4())
        st.session_state.messages = []
    refresh_backend_data()
    st.rerun()


# Render Sidebar
active_role = render_sidebar(
    config_status=st.session_state.config_status,
    conversations=st.session_state.conversations,
    current_conv_id=st.session_state.conversation_id,
    on_new_chat=handle_new_chat,
    on_select_conv=handle_select_conv,
    on_delete_conv=handle_delete_conv,
)

# Main Workspace Header
col_title, col_status = st.columns([0.75, 0.25])
with col_title:
    st.markdown("## ⚖️ GST Practice Copilot — India")
    st.markdown("*Autonomous Legal Research & Advisory Engine for Indian Chartered Accountants and Tax Advocates*")
with col_status:
    st.markdown(
        f"<div style='text-align: right; padding-top: 10px;'>"
        f"<span style='background-color: #e3f2fd; color: #0d47a1; padding: 4px 10px; border-radius: 12px; font-weight: 600; font-size: 0.85em;'>"
        f"Mode: {active_role}</span></div>",
        unsafe_allow_html=True,
    )

# Backend Connectivity Check
health = api_client.get_health()
if health.get("status") == "unreachable":
    st.error(
        "⚠️ **FastAPI Backend Offline**: Unable to connect to `http://127.0.0.1:8000`.\n\n"
        "Please ensure the backend is running via:\n"
        "```bash\n"
        "uvicorn backend.app.main:app --host 127.0.0.1 --port 8000\n"
        "```",
        icon="🚨",
    )

# Optional Document / Notice Upload
with st.expander("📎 Attach GST Notice, Return Copy or Agreement (PDF / TXT)", expanded=False):
    uploaded_file = st.file_uploader(
        "Upload client document for fact extraction (Max 20MB)",
        type=["pdf", "txt", "html"],
        key="file_uploader",
    )
    if uploaded_file is not None and st.button("Process & Attach Document"):
        with st.spinner("Uploading and analyzing document..."):
            try:
                res = api_client.upload_document(uploaded_file.name, uploaded_file.getvalue())
                st.session_state.uploaded_attachment_ids.append(res.get("file_id"))
                st.success(f"Attached `{uploaded_file.name}` (SHA: `{res.get('sha256_hash')[:8]}`)", icon="✅")
            except Exception as e:
                st.error(f"Upload failed: {e}")

st.divider()

# Welcome screen when conversation is empty
if not st.session_state.messages:
    st.info(
        "👋 **Welcome to GST Practice Copilot**.\n\n"
        "Ask any complex Indian GST query to produce a complete **12-Section Legal Research Memorandum**.\n\n"
        "**Example Legal Queries to Try:**\n"
        "- *What is the legal position on availing ITC after the due date under Section 16(4) following Finance (No. 2) Act, 2024?*\n"
        "- *Is GST applicable on remuneration paid to executive directors under reverse charge mechanism (RCM)?*\n"
        "- *Determine the place of supply for cross-border software support services where recipient is in Germany under Section 13 of IGST Act.*\n"
        "- *Can departmental audit proceedings be initiated under Section 65 after issuance of SCN under Section 73?*\n"
    )

# Render Chat History
for idx, msg in enumerate(st.session_state.messages):
    role = msg.get("role", "user")
    content = msg.get("content", "")
    metadata = msg.get("metadata", {})

    with st.chat_message(role):
        st.markdown(content)

        # Render Evidence Panel if available in metadata or message
        evidence = metadata.get("evidence", [])
        if evidence:
            render_evidence_panel(evidence)

        # Download button for assistant responses
        if role == "assistant" and content and not content.startswith("Error"):
            st.download_button(
                label="📥 Download Research Memorandum (.md)",
                data=content,
                file_name=f"GST_Research_Memorandum_{st.session_state.conversation_id[:8]}.md",
                mime="text/markdown",
                key=f"dl_{idx}",
            )

# Chat Input Box
user_prompt = st.chat_input("Enter your GST query, dispute, or compliance issue...")

if user_prompt:
    # 1. Display user query immediately
    with st.chat_message("user"):
        st.markdown(user_prompt)

    st.session_state.messages.append({
        "role": "user",
        "content": user_prompt,
        "metadata": {"user_role": active_role},
    })

    # 2. Execute research through backend with real-time SSE streaming
    with st.chat_message("assistant"):
        with st.status("🔍 Initializing GST Legal Research Engine...", expanded=True) as status_box:
            completed_nodes: set[str] = set()
            answer_text = ""
            evidence_list: list[dict] = []
            research_id = None
            needs_clarification = False

            try:
                for event_data in api_client.stream_chat(
                    query=user_prompt,
                    conversation_id=st.session_state.conversation_id,
                    user_role=active_role,
                    attachment_ids=st.session_state.uploaded_attachment_ids,
                ):
                    event_type = event_data.get("event")

                    if event_type == "started":
                        status_box.update(label="🚀 GST Legal Research Pipeline Active...", state="running")

                    elif event_type == "step":
                        node = event_data.get("node", "")
                        label = event_data.get("label", node)
                        if node not in completed_nodes:
                            completed_nodes.add(node)
                            # Render milestone updates with clear badges
                            if node in ("query_understanding", "fact_extraction"):
                                st.write(f"📋 **Stage 1/5:** {label}")
                                status_box.update(label=f"🔍 Stage 1/5: {label}...")
                            elif node in ("research_planner", "search_query_generation", "official_source_search"):
                                st.write(f"📑 **Stage 2/5:** {label}")
                                status_box.update(label=f"🌐 Stage 2/5: {label}...")
                            elif node in ("source_fetcher", "document_extractor", "evidence_compiler"):
                                st.write(f"📥 **Stage 3/5:** {label}")
                                status_box.update(label=f"📜 Stage 3/5: {label}...")
                            elif node in ("legal_analysis", "citation_validator"):
                                st.write(f"⚖️ **Stage 4/5:** {label}")
                                status_box.update(label=f"⚖️ Stage 4/5: {label}...")
                            elif node in ("answer_generator", "persistence_node"):
                                st.write(f"✍️ **Stage 5/5:** {label}")
                                status_box.update(label=f"✍️ Stage 5/5: {label}...")

                    elif event_type == "complete":
                        answer_text = event_data.get("answer", "")
                        evidence_list = event_data.get("evidence", [])
                        research_id = event_data.get("research_id")
                        needs_clarification = event_data.get("needs_clarification", False)
                        status_box.update(label="✅ Legal Research Memorandum Completed", state="complete", expanded=False)

                    elif event_type == "error":
                        raise RuntimeError(event_data.get("detail", "Unknown error during streaming"))

                if not answer_text:
                    # Fallback if streaming ended without answer
                    resp = api_client.get_conversation(st.session_state.conversation_id)
                    if resp and resp[-1].get("role") == "assistant":
                        answer_text = resp[-1].get("content", "")

                st.markdown(answer_text)

                if evidence_list:
                    render_evidence_panel(evidence_list)

                # Append assistant message to session state
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer_text,
                    "metadata": {
                        "research_id": research_id,
                        "evidence": evidence_list,
                        "needs_clarification": needs_clarification,
                    },
                })

                # Refresh sidebar conversations
                refresh_backend_data()

                st.download_button(
                    label="📥 Download Research Memorandum (.md)",
                    data=answer_text,
                    file_name=f"GST_Research_Memorandum_{st.session_state.conversation_id[:8]}.md",
                    mime="text/markdown",
                    key="dl_latest",
                )

            except Exception as e:
                status_box.update(label="❌ Research Failed", state="error", expanded=True)
                st.error(f"Failed to complete research: {e}")
