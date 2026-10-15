"""Middleware components for the dashboard."""

from middleware.csp_nonce import CSPNonceMiddleware, get_csp_nonce

__all__ = ["CSPNonceMiddleware", "get_csp_nonce"]
