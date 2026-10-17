from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.repositories.database import Database
from app.services.embeddings import create_embedder
from app.services.recommendation import RecommendationService


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich article records with embeddings and clusters.")
    parser.add_argument("--reembed", action="store_true", help="Re-embed records even when metadata matches.")
    args = parser.parse_args()
    settings = get_settings()
    embedder = create_embedder(
        settings.embedding_backend, settings.embedding_dimensions, settings.embedding_allow_fallback
    )
    service = RecommendationService(
        Database(settings.database_path),
        freshness_hours=settings.freshness_hours,
        topic_threshold=(
            settings.real_topic_match_threshold
            if embedder.name == "sentence_transformer" else settings.topic_match_threshold
        ),
        dimensions=settings.embedding_dimensions,
        embedder=embedder,
        cluster_similarity_threshold=(
            settings.cluster_similarity_threshold
            if embedder.name == "sentence_transformer"
            else settings.hashed_cluster_similarity_threshold
        ),
        cluster_window_hours=settings.cluster_window_hours,
    )
    print(f"Embedded {service.embed_all_articles(args.reembed)} articles with {embedder.name}.")


if __name__ == "__main__":
    main()
