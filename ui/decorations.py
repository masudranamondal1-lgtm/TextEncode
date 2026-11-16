import streamlit as st

def network_ornament():
    svg = """
    <svg width="100%" height="80" viewBox="0 0 400 80" fill="none" xmlns="http://www.w3.org/2000/svg" style="opacity: 0.15; margin-bottom: 20px;">
        <circle cx="50" cy="40" r="4" fill="currentColor"/>
        <circle cx="150" cy="20" r="6" fill="currentColor"/>
        <circle cx="250" cy="60" r="5" fill="currentColor"/>
        <circle cx="350" cy="30" r="7" fill="currentColor"/>
        <line x1="50" y1="40" x2="150" y2="20" stroke="currentColor" stroke-width="1.5"/>
        <line x1="150" y1="20" x2="250" y2="60" stroke="currentColor" stroke-width="1.5"/>
        <line x1="250" y1="60" x2="350" y2="30" stroke="currentColor" stroke-width="1.5"/>
        <line x1="50" y1="40" x2="250" y2="60" stroke="currentColor" stroke-width="0.5" stroke-dasharray="2 2"/>
    </svg>
    """
    st.markdown(f'<div style="color: var(--text);">{svg}</div>', unsafe_allow_html=True)

def section_divider():
    st.markdown("""
    <div style="display: flex; align-items: center; margin: 30px 0;">
        <div style="flex: 1; height: 1px; background: var(--border);"></div>
        <div style="margin: 0 15px; font-family: 'Source Serif 4', serif; color: var(--accent);">❖</div>
        <div style="flex: 1; height: 1px; background: var(--border);"></div>
    </div>
    """, unsafe_allow_html=True)
