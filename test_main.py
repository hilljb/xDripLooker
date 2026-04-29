import pytest
from unittest.mock import patch, MagicMock
from flask import Flask, Request
from main import process_xdrip_payload


@pytest.fixture
def app():
    """Minimal Flask app to provide an application context for jsonify()."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def mock_request():
    request = MagicMock(spec=Request)
    request.get_json.return_value = {
        "sgv": 120,
        "direction": "Flat",
        "_is_test_record": True,
    }
    return request


@patch("main.bq_client.insert_rows_json")
def test_successful_payload_parsing(mock_insert, mock_request, app):
    mock_insert.return_value = []  # No errors from BigQuery

    with app.app_context():
        response, status_code = process_xdrip_payload(mock_request)

    assert status_code == 200
    assert response.json["status"] == "success"
    assert response.json["is_test"] is True
    mock_insert.assert_called_once()