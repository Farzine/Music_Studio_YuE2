"""Uniform error envelope.

Every failure the client sees has a taxonomy code and, where one exists,
actionable guidance. Validation never happens only in the browser.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from yue2_studio_core.errors import GUIDANCE, ErrorCode, StudioError

logger = logging.getLogger(__name__)

_STATUS = {
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INVALID_CONFIG: 422,
    ErrorCode.INVALID_ABC: 422,
    ErrorCode.AUDIO_INPUT_ERROR: 422,
    ErrorCode.UNSUPPORTED_CAPABILITY: 409,
}


def register_error_handlers(app) -> None:
    @app.exception_handler(StudioError)
    async def _studio_error(_: Request, exc: StudioError):
        status = _STATUS.get(exc.code, 500)
        if status >= 500:
            logger.error(exc.message, extra={"error_code": exc.code.value}, exc_info=exc)
        return JSONResponse(status_code=status, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error_code": ErrorCode.INVALID_CONFIG.value,
                "error_message": "The request did not pass validation.",
                "guidance": GUIDANCE[ErrorCode.INVALID_CONFIG],
                "details": {"errors": exc.errors()},
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content={
                "error_code": ErrorCode.UNKNOWN.value,
                "error_message": str(exc),
                "guidance": GUIDANCE[ErrorCode.UNKNOWN],
                "details": {},
            },
        )
