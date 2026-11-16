import streamlit as st
import pandas as pd
import json
from database import db

def render_taxonomy_manager():
    st.header("Taxonomy Manager")
    st.write("Manage your reusable Entity Categories, Subcategories, and Relationship Types.")

    with db.get_connection() as conn:
        profiles = db.get_profiles(conn)
    
    if not profiles:
        st.error("No taxonomy profiles found. Please restart the app to reset.")
        return
        
    profile_options = {p["name"]: p["profile_id"] for p in profiles}
    selected_profile_name = st.selectbox("Active Taxonomy Profile", list(profile_options.keys()))
    profile_id = profile_options[selected_profile_name]

    tab_cat, tab_rel, tab_meta, tab_io = st.tabs([
        "📁 Entity Categories", "🔗 Relationship Types", "⚙️ Custom Metadata", "📦 Import / Export"
    ])

    # --- TAB 1: ENTITY CATEGORIES ---
    with tab_cat:
        with db.get_connection() as conn:
            cats = db.get_categories(conn, profile_id)
            
        cat_options = {c["name"]: c["category_id"] for c in cats}
        
        with st.form("add_category"):
            st.subheader("Add Category / Subcategory")
            col1, col2, col3 = st.columns(3)
            cat_name = col1.text_input("Category Name *")
            parent = col2.selectbox("Parent Category (Optional)", [None] + list(cat_options.keys()))
            color = col3.color_picker("Highlight Color", "#808080")
            cat_desc = st.text_input("Description")
            
            if st.form_submit_button("Add Category"):
                if cat_name.strip():
                    parent_id = cat_options.get(parent) if parent else None
                    with db.get_connection() as conn:
                        db.save_category(conn, profile_id=profile_id, name=cat_name.strip(), description=cat_desc, parent_id=parent_id)
                    st.success(f"Category '{cat_name}' added.")
                    st.rerun()
                    
        st.subheader("Current Categories")
        if cats:
            df = pd.DataFrame([dict(c) for c in cats])
            st.dataframe(df[["category_id", "parent_id", "name", "description"]], hide_index=True)

    # --- TAB 2: RELATIONSHIP TYPES ---
    with tab_rel:
        with db.get_connection() as conn:
            rels = db.get_relationship_types(conn, profile_id)
            
        with st.form("add_relationship"):
            st.subheader("Add Relationship Type")
            col1, col2 = st.columns(2)
            rel_name = col1.text_input("Relationship Name *", placeholder="e.g. flows_through")
            group = col2.text_input("Group", value="General")
            rel_desc = st.text_input("Description")
            directed = st.checkbox("Is Directed?", value=True)
            
            if st.form_submit_button("Add Relationship Type"):
                if rel_name.strip():
                    with db.get_connection() as conn:
                        db.save_relationship_type(conn, profile_id=profile_id, group_name=group, name=rel_name.strip(), description=rel_desc, directed=1 if directed else 0)
                    st.success(f"Relationship '{rel_name}' added.")
                    st.rerun()

        st.subheader("Current Relationship Types")
        if rels:
            df = pd.DataFrame([dict(r) for r in rels])
            st.dataframe(df[["type_id", "group_name", "name", "directed", "description"]], hide_index=True)

    # --- TAB 3: CUSTOM METADATA ---
    with tab_meta:
        with db.get_connection() as conn:
            attrs = db.get_attribute_definitions(conn, profile_id)
        
        with st.form("add_attribute"):
            st.subheader("Add Custom Metadata Field")
            col1, col2, col3 = st.columns(3)
            target = col1.selectbox("Applies To", ["entities", "relationships"])
            attr_name = col2.text_input("Attribute Name *", placeholder="e.g. Basin, Length")
            data_type = col3.selectbox("Data Type", ["text", "integer", "decimal", "date", "boolean", "json"])
            
            if st.form_submit_button("Add Attribute"):
                if attr_name.strip():
                    with db.get_connection() as conn:
                        db.save_attribute_definition(conn, profile_id=profile_id, target_table=target, category_id=None, name=attr_name.strip(), data_type=data_type, description="")
                    st.success(f"Attribute '{attr_name}' added.")
                    st.rerun()
                    
        st.subheader("Current Attributes")
        if attrs:
            df = pd.DataFrame([dict(a) for a in attrs])
            st.dataframe(df[["attribute_id", "target_table", "name", "data_type"]], hide_index=True)

    # --- TAB 4: IMPORT / EXPORT ---
    with tab_io:
        st.subheader("Export Profile")
        st.write("Download this taxonomy as a JSON file to share with other researchers or back it up.")
        with db.get_connection() as conn:
            profile_data = db.export_profile(conn, profile_id)
            json_str = json.dumps(profile_data, ensure_ascii=False, indent=2)
            
        st.download_button(
            label="📥 Download Taxonomy JSON",
            data=json_str.encode("utf-8"),
            file_name=f"textencode_taxonomy_{profile_id}.json",
            mime="application/json"
        )
        
        st.divider()
        
        st.subheader("Import Profile")
        st.write("Upload a previously exported JSON taxonomy. This will create a **new profile** so you don't overwrite your current work.")
        
        uploaded_file = st.file_uploader("Upload JSON", type=["json"])
        if uploaded_file is not None:
            try:
                data = json.load(uploaded_file)
                if st.button("Confirm Import", type="primary"):
                    with db.get_connection() as conn:
                        new_id = db.import_profile(conn, data)
                    st.success(f"Successfully imported taxonomy as a new profile (ID: {new_id}). Please select it from the dropdown above.")
                    st.rerun()
            except Exception as e:
                st.error(f"Invalid JSON file: {e}")
