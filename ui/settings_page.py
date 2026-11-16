import streamlit as st
from ui import components

def render_settings():
    components.page_header("Appearance Settings", "Customise your research environment.")
    
    st.subheader("Display Mode")
    theme = st.radio("Theme", ["Classic Light", "Dark Research", "Eye Comfort", "High Contrast"], 
                     index=["Classic Light", "Dark Research", "Eye Comfort", "High Contrast"].index(st.session_state.get("theme_mode", "Classic Light")),
                     horizontal=True)
    if theme != st.session_state.get("theme_mode"):
        st.session_state.theme_mode = theme
        st.rerun()
        
    st.divider()
    
    st.subheader("Reading Experience")
    col1, col2, col3 = st.columns(3)
    with col1:
        font_size = st.slider("Font Size (rem)", 0.8, 1.5, st.session_state.get("reading_font_size", 1.15), 0.05)
    with col2:
        line_height = st.slider("Line Spacing", 1.2, 2.5, st.session_state.get("reading_line_height", 1.8), 0.1)
    with col3:
        width = st.slider("Reading Width (px)", 500, 1200, st.session_state.get("reading_width", 800), 50)
        
    if font_size != st.session_state.get("reading_font_size") or line_height != st.session_state.get("reading_line_height") or width != st.session_state.get("reading_width"):
        st.session_state.reading_font_size = font_size
        st.session_state.reading_line_height = line_height
        st.session_state.reading_width = width
        st.rerun()

    st.button("Reset to Defaults", on_click=lambda: st.session_state.update({"reading_font_size": 1.15, "reading_line_height": 1.8, "reading_width": 800, "theme_mode": "Classic Light"}))
