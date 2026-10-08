"""FastAPI-specific adapter for ServiceProxy.

Converts the library's HTTPException to FastAPI's HTTPException.
"""

from fastapi import HTTPException as FastAPIHTTPException

from .proxy import HTTPException as LibHTTPException
from .proxy import ServiceProxy as BaseServiceProxy


class ServiceProxy(BaseServiceProxy):
    """ServiceProxy that raises FastAPI HTTPExceptions.

    This subclass wraps the base ServiceProxy methods to convert
    the library's HTTPException to FastAPI's HTTPException.
    """

    async def get(self, path, **kwargs):
        """GET request with FastAPI exception conversion."""
        try:
            return await super().get(path, **kwargs)
        except LibHTTPException as e:
            raise FastAPIHTTPException(status_code=e.status_code, detail=e.detail)

    async def post(self, path, **kwargs):
        """POST request with FastAPI exception conversion."""
        try:
            return await super().post(path, **kwargs)
        except LibHTTPException as e:
            raise FastAPIHTTPException(status_code=e.status_code, detail=e.detail)

    async def put(self, path, **kwargs):
        """PUT request with FastAPI exception conversion."""
        try:
            return await super().put(path, **kwargs)
        except LibHTTPException as e:
            raise FastAPIHTTPException(status_code=e.status_code, detail=e.detail)

    async def delete(self, path, **kwargs):
        """DELETE request with FastAPI exception conversion."""
        try:
            return await super().delete(path, **kwargs)
        except LibHTTPException as e:
            raise FastAPIHTTPException(status_code=e.status_code, detail=e.detail)

    async def forward_request(self, request, path, **kwargs):
        """Forward request with FastAPI exception conversion."""
        try:
            return await super().forward_request(request, path, **kwargs)
        except LibHTTPException as e:
            raise FastAPIHTTPException(status_code=e.status_code, detail=e.detail)
