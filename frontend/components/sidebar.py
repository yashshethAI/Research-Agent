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
        search_reachable = config_status.get("search_reachable")
        search_provider = config_status.get("search_provider", "searxng")
        search_base_url = config_status.get("search_base_url")
        search_status_msg = config_status.get("search_status_message")

        if llm_ready:
            st.success(f"🟢 LLM: {config_status.get('llm_model') or 'Configured'}", icon="✅")
        else:
            st.warning("🟠 LLM: Not Configured (OpenAI-compatible)", icon="⚠️")

        if not search_ready:
            st.warning(f"⚪ Search: {search_provider.upper()} URL Required", icon="ℹ️")
        elif search_reachable is False:
            st.warning(f"🟠 Search: {search_provider.upper()} Unreachable", icon="⚠️")
            if search_status_msg:
                st.caption(search_status_msg)
        else:
            st.success(f"🟢 Search: {search_provider.upper()} Ready", icon="🔍")

        with st.expander("🛠️ Connection Details", expanded=False):
            st.write(f"**Base URL:** `{config_status.get('llm_base_url') or 'Not Set'}`")
            st.write(f"**Search Provider:** `{search_provider}`")
            st.write(f"**Search URL:** `{search_base_url or 'Not Set'}`")
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
