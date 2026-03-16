#!/usr/bin/env python3
"""
Automated Landsat data download utility.

Downloads Landsat 8/9 Collection 2 Level-2 scenes from USGS EarthExplorer
for the configured study area and date range.

Requires a USGS EarthExplorer account. Set credentials via environment:
    export USGS_USERNAME=your_username
    export USGS_PASSWORD=your_password

Usage:
    python scripts/download_data.py --config config.yaml --output data/
"""

import argparse
import os
import sys
import json
import logging
import requests
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.utils import load_config, ensure_directory

logger = logging.getLogger(__name__)

USGS_API_URL = "https://m2m.cr.usgs.gov/api/api/json/stable"


class USGSDataDownloader:
    """Downloads Landsat scenes from USGS M2M API."""

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.api_key = None

    def login(self) -> None:
        """Authenticate with USGS M2M API."""
        payload = {"username": self.username, "password": self.password}
        response = requests.post(f"{USGS_API_URL}/login", json=payload)
        result = response.json()

        if result.get("errorCode"):
            raise RuntimeError(f"USGS login failed: {result['errorMessage']}")

        self.api_key = result["data"]
        logger.info("Successfully authenticated with USGS M2M API")

    def search_scenes(
        self,
        bbox: list,
        date_start: str,
        date_end: str,
        cloud_cover_max: int = 10,
        dataset: str = "landsat_ot_c2_l2",
    ) -> list:
        """
        Search for Landsat scenes matching criteria.

        Args:
            bbox: [west, south, east, north]
            date_start: start date (YYYY-MM-DD)
            date_end: end date (YYYY-MM-DD)
            cloud_cover_max: maximum cloud cover percentage
            dataset: USGS dataset name

        Returns:
            list of scene metadata dicts
        """
        spatial_filter = {
            "filterType": "mbr",
            "lowerLeft": {"longitude": bbox[0], "latitude": bbox[1]},
            "upperRight": {"longitude": bbox[2], "latitude": bbox[3]},
        }

        acquisition_filter = {
            "start": date_start,
            "end": date_end,
        }

        cloud_filter = {"min": 0, "max": cloud_cover_max}

        payload = {
            "datasetName": dataset,
            "spatialFilter": spatial_filter,
            "temporalFilter": acquisition_filter,
            "cloudCoverFilter": cloud_filter,
            "maxResults": 50,
        }

        headers = {"X-Auth-Token": self.api_key}
        response = requests.post(
            f"{USGS_API_URL}/scene-search", json=payload, headers=headers
        )
        result = response.json()

        if result.get("errorCode"):
            raise RuntimeError(f"Scene search failed: {result['errorMessage']}")

        scenes = result["data"]["results"]
        logger.info(f"Found {len(scenes)} scenes matching search criteria")

        return scenes

    def download_scene(self, entity_id: str, output_dir: str) -> str:
        """
        Download a Landsat scene by entity ID.

        Args:
            entity_id: USGS entity ID for the scene
            output_dir: directory to save downloaded files

        Returns:
            path to downloaded file
        """
        headers = {"X-Auth-Token": self.api_key}

        # Request download URL
        payload = {
            "datasetName": "landsat_ot_c2_l2",
            "entityIds": [entity_id],
        }
        response = requests.post(
            f"{USGS_API_URL}/download-options", json=payload, headers=headers
        )
        options = response.json()["data"]

        if not options:
            raise RuntimeError(f"No download options for entity: {entity_id}")

        # Get the bundle download
        download_id = options[0]["id"]
        download_payload = {
            "downloads": [{"entityId": entity_id, "productId": download_id}]
        }
        response = requests.post(
            f"{USGS_API_URL}/download-request",
            json=download_payload,
            headers=headers,
        )
        download_url = response.json()["data"]["availableDownloads"][0]["url"]

        # Download file
        output_path = Path(output_dir) / f"{entity_id}.tar.gz"
        logger.info(f"Downloading {entity_id} to {output_path}")

        with requests.get(download_url, stream=True) as r:
            r.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        logger.info(f"Download complete: {output_path}")
        return str(output_path)

    def logout(self) -> None:
        """Logout from USGS API."""
        if self.api_key:
            headers = {"X-Auth-Token": self.api_key}
            requests.post(f"{USGS_API_URL}/logout", headers=headers)
            logger.info("Logged out of USGS M2M API")


def main():
    parser = argparse.ArgumentParser(description="Download Landsat data from USGS")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--output", default="data", help="Output directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    username = os.environ.get("USGS_USERNAME")
    password = os.environ.get("USGS_PASSWORD")
    if not username or not password:
        logger.error(
            "Set USGS_USERNAME and USGS_PASSWORD environment variables"
        )
        sys.exit(1)

    config = load_config(args.config)
    output_dir = ensure_directory(args.output)

    downloader = USGSDataDownloader(username, password)
    try:
        downloader.login()

        scenes = downloader.search_scenes(
            bbox=config["study_area"]["bbox"],
            date_start=config["landsat"]["date_range"]["start"],
            date_end=config["landsat"]["date_range"]["end"],
            cloud_cover_max=config["landsat"]["cloud_cover_max"],
        )

        for scene in scenes[:3]:  # Download top 3 scenes
            downloader.download_scene(scene["entityId"], str(output_dir))

    finally:
        downloader.logout()


if __name__ == "__main__":
    main()
