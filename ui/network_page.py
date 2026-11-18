
import streamlit as st
from streamlit_agraph import agraph, Node, Edge, Config

from database import db
from ui import components


def render_network_analysis():
    components.page_header(
        "Network Analysis",
        "Visualise relationships between entities across your research.",
    )

    with db.get_connection() as conn:
        documents = db.list_documents(conn)

    scope_options = {
        "All relationships": None,
        "Unassigned / legacy relationships": "__unscoped__",
    }

    for document in documents:
        scope_options[
            f"{document['doc_id']} — {document['title']}"
        ] = document["doc_id"]

    selected_scope = st.selectbox(
        "Relationship scope",
        list(scope_options),
        key="network_relationship_scope",
    )

    scope_id = scope_options[selected_scope]

    with db.get_connection() as conn:
        if scope_id == "__unscoped__":
            relationships = db.get_relationships(
                conn, unscoped_only=True
            )
        elif scope_id is None:
            relationships = db.get_relationships(conn)
        else:
            relationships = db.get_relationships(
                conn, doc_id=scope_id
            )

    st.caption(
        f"{len(relationships)} relationship(s) in this view."
    )

    if not relationships:
        st.info("No relationships found for this scope.")
        return

    nodes = {}
    edges = []

    for relation in relationships:
        source = relation["source_name"]
        target = relation["target_name"]

        if source not in nodes:
            nodes[source] = Node(
                id=source,
                label=source,
                size=20,
                color="#244C56",
            )

        if target not in nodes:
            nodes[target] = Node(
                id=target,
                label=target,
                size=20,
                color="#A7895B",
            )

        edges.append(
            Edge(
                source=source,
                target=target,
                label=relation["type_name"],
                color="#E5E2DB",
            )
        )

    config = Config(
        width="100%",
        height=600,
        directed=True,
        physics=True,
        hierarchical=False,
        nodeHighlightBehavior=True,
        highlightColor="#F7A7A6",
        collapsible=False,
    )

    st.write("Drag nodes to explore the network. Scroll to zoom.")

    agraph(
        nodes=list(nodes.values()),
        edges=edges,
        config=config,
    )

    for relation in relationships:
        with st.container(border=True):
            st.markdown(
                f"**{relation['source_name']}** "
                f"`[{relation['type_name']}]` **{relation['target_name']}**"
            )
            st.caption(
                f"{relation['relationship_id']} · "
                f"Document: {relation['doc_id'] or 'Unassigned / legacy'}"
            )
            if relation["description"]:
                st.write(relation["description"])
            confirm = st.checkbox(
                "Confirm moving to Trash",
                key=f"confirm_network_trash_{relation['relationship_id']}",
            )
            if st.button(
                "Move to Trash",
                disabled=not confirm,
                key=f"network_trash_{relation['relationship_id']}",
            ):
                with db.get_connection() as conn:
                    db.soft_delete_relationship(conn, relation["relationship_id"])
                st.rerun()

    with st.expander("Relationship data"):
        st.dataframe(
            [
                {
                    "relationship_id": r["relationship_id"],
                    "source_entity_id": r["source_entity_id"],
                    "target_entity_id": r["target_entity_id"],
                    "source_name": r["source_name"],
                    "target_name": r["target_name"],
                    "type_name": r["type_name"],
                    "doc_id": r["doc_id"],
                    "description": r["description"],
                    "confidence": r["confidence"],
                }
                for r in relationships
            ],
            hide_index=True,
            width="stretch",
        )
