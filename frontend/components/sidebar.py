from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st


def render_sidebar(
    config_status: dict[str, Any],
    conversations: list[dict[str, Any]],
    current_conv_id: str,
    on_new_chat: Callable[[], None],
    on_select_conv: Callable[[str], None],
    on_delete_conv: Callable[[str], None],
) -> str:
    """Renders the professional CA firm sidebar."""
    with st.sidebar:
        st.markdown("### ⚖️ GST Practice Copilot")
        st.caption("AI Legal Research Agent for Indian Tax Professionals")

        if st.button("➕ New Legal Query", use_container_width=True, type="primary"):
            on_new_chat()

        st.divider()

        # Role / Mode Selection
        st.markdown("#### 👤 Advisory Persona")
        roles = ["Professional", "Intern / Article Assistant", "Partner / Counsel"]
        selected_role = st.selectbox(
            "Select Practice Mode",
            options=roles,
            index=0,
            help="Adapts checklist priority, depth of portal procedure, and procedural emphasis in the final memorandum.",
        )

        st.divider()

        # System Status
        st.markdown("#### 🔌 Engine Status")
        llm_ready = config_status.get("llm_configured", False)
        search_ready = config_status.get("search_configured", False)
        search_provider = config_status.get("search_provider", "tavily")

        if llm_ready:
            st.success(f"🟢 LLM: {config_status.get('llm_model') or 'Configured'}", icon="✅")
        else:
            st.warning("🟠 LLM: Not Configured (OpenAI-compatible)", icon="⚠️")

        if search_ready:
            st.success(f"🟢 Search: {search_provider.upper()} Ready", icon="🔍")
        else:
            st.info(f"⚪ Search: {search_provider.upper()} Key Required", icon="ℹ️")

        with st.expander("🛠️ Connection Details", expanded=False):
            st.write(f"**Base URL:** `{config_status.get('llm_base_url') or 'Not Set'}`")
            st.write(f"**Allowed Domains:** {config_status.get('official_domains_count', 0)} official portals")
            st.write("**Storage Engine:** Filesystem (Local)")

        st.divider()

        # Conversation History
        st.markdown("#### 📁 Research Sessions")
        if not conversations:
            st.caption("No previous research sessions found.")
        else:
            for conv in conversations:
                cid = conv.get("conversation_id", "")
                title = conv.get("title", f"Session {cid[:8]}")
                msg_count = conv.get("message_count", 0)

                col_btn, col_del = st.columns([0.82, 0.18])
                with col_btn:
                    btn_type = "secondary" if cid != current_conv_id else "primary"
                    if st.button(f"{title[:28]} ({msg_count})", key=f"conv_{cid}", use_container_width=True, type=btn_type):
                        on_select_conv(cid)
                with col_del:
                    if st.button("🗑️", key=f"del_{cid}", help="Delete this session"):
                        on_delete_conv(cid)

        return selected_role
