import streamlit as st
import pandas as pd
from database import db
from ui import components

def render_spatial_analysis():
    components.page_header("Spatial Analysis", "Map entities with geographical coordinates.")
    
    with db.get_connection() as conn:
        profiles = db.get_profiles(conn)
        profile_id = profiles[0]["profile_id"] if profiles else 1
        entities = db.get_entities(conn, profile_id)
        
    tab_map, tab_manage = st.tabs(["🗺️ Map View", "⚙️ Manage Coordinates"])
    
    with tab_map:
        mapped_entities = [e for e in entities if e["latitude"] is not None and e["longitude"] is not None]
        if not mapped_entities:
            components.empty_state("No entities have coordinates yet. Go to 'Manage Coordinates' to add them.")
        else:
            df = pd.DataFrame([{
                "name": e["canonical_name"],
                "lat": e["latitude"],
                "lon": e["longitude"],
                "category": e["category_name"]
            } for e in mapped_entities])
            
            st.write(f"Showing {len(df)} mapped entities.")
            st.map(df, latitude="lat", longitude="lon", size=20, color="#244C56")
            st.dataframe(df[["name", "category", "lat", "lon"]], hide_index=True, use_container_width=True)

    with tab_manage:
        st.subheader("Add or Edit Coordinates")
        entity_options = {f"{e['entity_id']} — {e['canonical_name']}": e for e in entities}
        if not entity_options:
            st.info("No entities available.")
            return
            
        selected_label = st.selectbox("Select Entity", list(entity_options.keys()))
        selected_entity = entity_options[selected_label]
        
        with st.form("edit_coords"):
            lat = st.number_input("Latitude", value=float(selected_entity["latitude"]) if selected_entity["latitude"] else 0.0, format="%.6f")
            lon = st.number_input("Longitude", value=float(selected_entity["longitude"]) if selected_entity["longitude"] else 0.0, format="%.6f")
            
            col1, col2 = st.columns(2)
            if col1.form_submit_button("Save Coordinates", type="primary"):
                with db.get_connection() as conn:
                    conn.execute("UPDATE entities SET latitude = ?, longitude = ? WHERE entity_id = ?", (lat, lon, selected_entity["entity_id"]))
                st.success("Coordinates updated.")
                st.rerun()
                
            if col2.form_submit_button("Clear Coordinates", type="secondary"):
                with db.get_connection() as conn:
                    conn.execute("UPDATE entities SET latitude = NULL, longitude = NULL WHERE entity_id = ?", (selected_entity["entity_id"],))
                st.warning("Coordinates removed.")
                st.rerun()
