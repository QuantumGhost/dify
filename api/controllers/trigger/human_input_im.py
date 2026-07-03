import logging

from flask import Response, jsonify, request

from controllers.trigger import bp
from services.human_input_im.feishu_ingress_service import FeishuIngressService

logger = logging.getLogger(__name__)


@bp.route("/human-input/im/feishu/callback", methods=["POST"])
def handle_feishu_human_input_callback():
    try:
        status_code, response_body = FeishuIngressService().handle_webhook_request(
            headers=request.headers,
            body=request.get_data(),
        )
        return Response(response_body, status=status_code, mimetype="application/json")
    except Exception:
        logger.exception("Feishu human input callback failed")
        return jsonify({"error": "Internal server error"}), 500
