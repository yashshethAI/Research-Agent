from __future__ import annotations

from typing import Any

import streamlit as st


def render_evidence_panel(evidence_records: list[dict[str, Any]]) -> None:
    """Renders structured, clickable legal evidence retrieved from official sources."""
    if not evidence_records:
        return

    with st.expander(f"📑 Verified Legal Evidence ({len(evidence_records)} Official Sources)", expanded=False):
        for e in evidence_records:
            src_id = e.get("source_id", "SRC")
            title = e.get("title", "Official Source")
            url = e.get("url", "#")
            authority = e.get("authority", "GST Authority")
            sec_rule = e.get("section_or_rule", "General Law")
            excerpt = e.get("excerpt", "")
            sha_hash = e.get("sha256_hash", "")[:12]

            st.markdown(
                f"""
                <div style="border: 1px solid #e0e0e0; border-radius: 6px; padding: 12px; margin-bottom: 12px; background-color: #fdfdfd;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span style="background-color: #0d47a1; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: bold;">
                            {src_id}
                        </span>
                        <span style="font-size: 0.8em; color: #666;">
                            <b>SHA-256:</b> <code>{sha_hash}</code>
                        </span>
                    </div>
                    <div style="font-size: 1.05em; font-weight: 600; margin-bottom: 4px;">
                        <a href="{url}" target="_blank" style="text-decoration: none; color: #1565c0;">
                            🔗 {title}
                        </a>
                    </div>
                    <div style="font-size: 0.85em; color: #444; margin-bottom: 8px;">
                        <b>Authority:</b> {authority} &nbsp;|&nbsp; <b>Provisions:</b> <code>{sec_rule}</code>
                    </div>
                    <div style="font-size: 0.9em; background-color: #f5f5f5; padding: 8px; border-radius: 4px; border-left: 3px solid #1976d2; font-family: monospace;">
                        {excerpt}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
