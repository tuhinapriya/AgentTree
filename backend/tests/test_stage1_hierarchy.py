from fastapi.testclient import TestClient

from backend.app.main import build_app


def test_valid_parent_and_two_children_registration(tmp_path):
    app = build_app(str(tmp_path / "stage1.db"))
    client = TestClient(app)

    run_response = client.post("/runs", json={"run_id": "run-1", "scenario": "customer-operations"})
    assert run_response.status_code == 200

    parent_response = client.post(
        "/runs/run-1/agents",
        json={
            "agent_id": "parent-agent",
            "role": "parent",
            "allowed_tools": ["read_orders", "process_order", "read_account", "modify_billing"],
        },
    )
    assert parent_response.status_code == 200
    assert parent_response.json()["agent_id"] == "parent-agent"

    order_response = client.post(
        "/runs/run-1/agents",
        json={
            "agent_id": "order-agent",
            "role": "order",
            "parent_agent_id": "parent-agent",
            "allowed_tools": ["read_orders", "process_order"],
        },
    )
    assert order_response.status_code == 200
    assert order_response.json()["parent_agent_id"] == "parent-agent"

    account_response = client.post(
        "/runs/run-1/agents",
        json={
            "agent_id": "account-agent",
            "role": "account",
            "parent_agent_id": "parent-agent",
            "allowed_tools": ["read_account"],
        },
    )
    assert account_response.status_code == 200
    assert account_response.json()["parent_agent_id"] == "parent-agent"


def test_duplicate_agent_id_is_rejected(tmp_path):
    app = build_app(str(tmp_path / "stage1-duplicate.db"))
    client = TestClient(app)

    client.post("/runs", json={"run_id": "run-duplicate", "scenario": "customer-operations"})
    client.post("/runs/run-duplicate/agents", json={"agent_id": "parent-agent", "role": "parent"})

    duplicate_response = client.post(
        "/runs/run-duplicate/agents",
        json={"agent_id": "parent-agent", "role": "child"},
    )
    assert duplicate_response.status_code == 409


def test_unknown_parent_is_rejected(tmp_path):
    app = build_app(str(tmp_path / "stage1-unknown.db"))
    client = TestClient(app)

    client.post("/runs", json={"run_id": "run-unknown", "scenario": "customer-operations"})
    unknown_parent_response = client.post(
        "/runs/run-unknown/agents",
        json={"agent_id": "child-agent", "role": "account", "parent_agent_id": "missing-agent"},
    )
    assert unknown_parent_response.status_code == 404


def test_cyclic_hierarchy_is_rejected(tmp_path):
    app = build_app(str(tmp_path / "stage1-cycle.db"))
    client = TestClient(app)

    client.post("/runs", json={"run_id": "run-cycle", "scenario": "customer-operations"})

    cycle_response = client.post(
        "/runs/run-cycle/agents",
        json={"agent_id": "self-cycle-agent", "role": "parent", "parent_agent_id": "self-cycle-agent"},
    )
    assert cycle_response.status_code == 409


def test_hierarchy_api_returns_tree_structure(tmp_path):
    app = build_app(str(tmp_path / "stage1-tree.db"))
    client = TestClient(app)

    client.post("/runs", json={"run_id": "run-tree", "scenario": "customer-operations"})
    client.post("/runs/run-tree/agents", json={"agent_id": "parent-agent", "role": "parent"})
    client.post(
        "/runs/run-tree/agents",
        json={"agent_id": "order-agent", "role": "order", "parent_agent_id": "parent-agent"},
    )
    client.post(
        "/runs/run-tree/agents",
        json={"agent_id": "account-agent", "role": "account", "parent_agent_id": "parent-agent"},
    )

    tree_response = client.get("/runs/run-tree/tree")
    assert tree_response.status_code == 200
    payload = tree_response.json()
    assert payload["run_id"] == "run-tree"
    assert len(payload["agents"]) == 3
    assert payload["tree"][0]["agent_id"] == "parent-agent"
    assert {child["agent_id"] for child in payload["tree"][0]["children"]} == {"order-agent", "account-agent"}
