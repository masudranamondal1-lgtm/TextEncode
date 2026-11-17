import streamlit as st
def page_header(title: str, subtitle: str = None):
    st.title(title)
    if subtitle: st.markdown(f"<p style='color: var(--text-muted); font-size: 1.05rem; margin-top: -10px; margin-bottom: 25px;'>{subtitle}</p>", unsafe_allow_html=True)
def metric_row(metrics: list[dict]):
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        with col: st.markdown(f"<div class='metric-container'><div class='metric-label'>{m['label']}</div><div class='metric-value'>{m['value']}</div></div>", unsafe_allow_html=True)
def empty_state(message: str, icon: str = "📭"):
    st.markdown(f"<div style='text-align: center; padding: 50px; background: var(--surface); border-radius: 8px; border: 1px dashed var(--border);'><div style='font-size: 2rem; margin-bottom: 10px;'>{icon}</div><div style='color: var(--text-muted);'>{message}</div></div>", unsafe_allow_html=True)
