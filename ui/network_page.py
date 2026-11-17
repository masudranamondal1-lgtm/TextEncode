import streamlit as st
from streamlit_agraph import agraph, Node, Edge, Config
from database import db
from ui import components

def render_network_analysis():
    components.page_header("Network Analysis", "Visualise relationships between entities.")
    
    with db.get_connection() as conn:
        rels = db.get_relationships(conn)
        
    tab_graph, tab_manage = st.tabs(["🕸️ Network Graph", "⚙️ Manage Relationships"])
    
    with tab_graph:
        if not rels:
            components.empty_state("No relationships found. Add some in 'Manage Relationships'.")
        else:
            nodes_dict = {}
            edges = []
            for r in rels:
                if r["source_name"] not in nodes_dict:
                    nodes_dict[r["source_name"]] = Node(id=r["source_name"], label=r["source_name"], size=20, color="#244C56")
                if r["target_name"] not in nodes_dict:
                    nodes_dict[r["target_name"]] = Node(id=r["target_name"], label=r["target_name"], size=20, color="#A7895B")
                edges.append(Edge(source=r["source_name"], target=r["target_name"], label=r["type_name"], color="#E5E2DB"))

            config = Config(width="100%", height=600, directed=True, physics=True, hierarchical=False, nodeHighlightBehavior=True, highlightColor="#F7A7A6", collapsible=False)
            st.write("Drag nodes to explore the network. Scroll to zoom.")
            agraph(nodes=list(nodes_dict.values()), edges=edges, config=config)
            
    with tab_manage:
        st.subheader("Delete Relationship")
        if not rels:
            st.info("No relationships to delete.")
        else:
            for r in rels:
                with st.container(border=True):
                    col1, col2 = st.columns([4, 1])
                    col1.markdown(f"**{r['source_name']}** `[{r['type_name']}]` **{r['target_name']}**")
                    if r['description']: col1.caption(r['description'])
                    if col2.button("🗑️ Delete", key=f"del_rel_{r['relationship_id']}", type="secondary"):
                        with db.get_connection() as conn: db.delete_relationship(conn, r['relationship_id'])
                        st.rerun()
