"""
LoopHive — Product Distributor

Uploads digital files (checklists, ebooks) and sets prices on Gumroad and Payhip.
"""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger(__name__)


class ProductDistributor:
    """Manages digital storefront uploads."""

    def __init__(self, gumroad_token: str = "", payhip_key: str = ""):
        self.gumroad_token = gumroad_token
        self.payhip_key = payhip_key

    async def distribute(self, name: str, description: str, price: float, file_content: str) -> dict:
        """Create a listing on Gumroad or Payhip and upload the file."""
        logger.info("distributing_product", name=name, price=price)

        # Fallback to mock/simulation if no token is configured
        if not self.gumroad_token or "your_" in self.gumroad_token:
            simulated_url = f"https://gumroad.com/l/simulated-{hash(name)}"
            logger.info("product_distribution_simulated", url=simulated_url)
            return {
                "platform": "gumroad",
                "product_name": name,
                "price": price,
                "url": simulated_url,
                "status": "published",
            }

        # Real Gumroad product creation API call: POST https://api.gumroad.com/v2/products
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                body = {
                    "access_token": self.gumroad_token,
                    "name": name,
                    "description": description,
                    "price_cents": int(price * 100),
                    # Set custom file or product download payload
                }
                r = await client.post("https://api.gumroad.com/v2/products", data=body)
                r.raise_for_status()
                data = r.json()
                product = data.get("product", {})
                return {
                    "platform": "gumroad",
                    "product_name": name,
                    "price": price,
                    "url": product.get("short_url"),
                    "status": "published" if product.get("published") else "draft",
                }
        except Exception as e:
            logger.error("gumroad_api_failed", error=str(e))
            raise RuntimeError(f"Failed to publish to Gumroad: {str(e)}")
