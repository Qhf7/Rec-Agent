"""Offline lexical retrieval ablation on synthetic canonical product data.

The primary weak target is explicit historical cart membership, held out from
all ranking inputs. Exact search-term matches are an auxiliary lexical recovery
target derived from the query, not independent relevance judgments. No human
gold labels, online effects, or embeddings are claimed. Optional learned_pairwise
fits a lightweight linear reranker on development cart weak labels only.

Run: python -m agent_benchmark.retrieval --output-dir runs/retrieval
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import random
import statistics
import time
from typing import Any, Iterable

from canonical_data import CANONICAL_SCHEMA_VERSION, load_canonical_items, load_canonical_users
from agent_benchmark.dataset import build_tasks

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("rule", "bm25", "hybrid")
LEARNED_METHOD = "learned_pairwise"
PAIRWISE_SEED = 20261120
PAIRWISE_FEATURES = ("preferred_category_match", "search_title_match_fraction", "search_category_match_fraction", "normalized_bm25", "query_category_bigram_overlap", "query_title_bigram_overlap", "season_match")
LABEL_SOURCES = ("cart", "search_exact", "union")
TEXT_FIELDS = ("title", "brand", "category_l1", "category_l2", "category_l3", "functions", "material", "spec")


def ranking_context(user: dict) -> dict[str, list[str]]:
    """Allowlist the only two user fields available to every ranker."""
    return {key: [str(x) for x in user.get(key, []) if isinstance(x, str) and x.strip()]
            for key in ("preferred_categories", "last_search_terms")}


def build_query(user: dict) -> str:
    context = ranking_context(user)
    return " ".join(context["preferred_categories"] + context["last_search_terms"])


def tokenize(text: str) -> list[str]:
    """Lowercase Latin words plus overlapping Chinese bigrams per text run."""
    tokens = []
    for run in re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", text.lower()):
        if re.fullmatch(r"[\u3400-\u9fff]+", run) and len(run) > 1:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
        else:
            tokens.append(run)
    return tokens


def item_text(item: dict) -> str:
    return " ".join(" ".join(str(x) for x in item.get(key, [])) if isinstance(item.get(key), list)
                    else str(item.get(key, "")) for key in TEXT_FIELDS)


def weak_labels(user: dict, items: dict[str, dict]) -> dict[str, set[str]]:
    """Build evaluation-only targets; no target IDs are passed to rankers.

    cart: exact recorded item IDs. search_exact: complete search phrase occurs
    verbatim in title/category_l3. union is reported separately. Stock filtering
    is applied only to returned candidates, so unavailable target products stay
    in the recall denominator; their count is disclosed in the report.
    """
    cart = {iid for iid in user.get("recent_cart_item_ids", []) if iid in items}
    terms = [t.strip().lower() for t in user.get("last_search_terms", []) if isinstance(t, str) and t.strip()]
    exact = {iid for iid, item in items.items() if any(term in (str(item.get("title", "")) + " " + str(item.get("category_l3", ""))).lower() for term in terms)}
    return {"cart": cart, "search_exact": exact, "union": cart | exact}


def ranking_metrics(ranked: Iterable[str], relevant: set[str], k: int = 10) -> dict[str, float | None]:
    """Binary weak-label Recall/MRR/NDCG; unlabeled queries return None."""
    if not relevant:
        return {"recall_at_10": None, "mrr_at_10": None, "ndcg_at_10": None}
    retrieved = list(dict.fromkeys(ranked))[:k]
    hit_positions = [index + 1 for index, iid in enumerate(retrieved) if iid in relevant]
    dcg = sum(1 / math.log2(position + 1) for position in hit_positions)
    ideal = sum(1 / math.log2(index + 2) for index in range(min(k, len(relevant))))
    return {"recall_at_10": len(hit_positions) / len(relevant),
            "mrr_at_10": 1 / hit_positions[0] if hit_positions else 0.0,
            "ndcg_at_10": dcg / ideal if ideal else 0.0}


class RetrievalIndex:
    """Small CPU lexical index; hybrid uses deterministic rules, not learning."""

    def __init__(self, items: dict[str, dict]):
        self.items = items
        self.documents = {iid: Counter(tokenize(item_text(item))) for iid, item in items.items()}
        self.lengths = {iid: sum(counts.values()) for iid, counts in self.documents.items()}
        self.avg_length = statistics.fmean(self.lengths.values()) if self.lengths else 1.0
        self.df = Counter(token for counts in self.documents.values() for token in counts)

    def _rule_scores(self, context: dict) -> dict[str, float]:
        prefs = context["preferred_categories"]
        terms = context["last_search_terms"]
        return {iid: 4.0 * (item.get("category_l1") in prefs) + 3.0 * any(term in item.get("title", "") for term in terms)
                for iid, item in self.items.items()}

    def _bm25_scores(self, context: dict) -> dict[str, float]:
        query = Counter(tokenize(build_query(context)))
        count = len(self.documents)
        scores = {}
        for iid, document in self.documents.items():
            score = 0.0
            for token, frequency in query.items():
                tf = document[token]
                if not tf:
                    continue
                idf = math.log(1 + (count - self.df[token] + 0.5) / (self.df[token] + 0.5))
                norm = tf + 1.5 * (1 - 0.75 + 0.75 * self.lengths[iid] / self.avg_length)
                score += frequency * idf * tf * 2.5 / norm
            scores[iid] = score
        return scores

    def rank(self, method: str, user: dict, *, k: int = 10, as_of: str = "2026-06-15") -> list[str]:
        """Rank using preference/search only; cart/history fields are discarded.

        rule reproduces the UI's category and lexical weights without cart or
        feedback. BM25 uses k1=1.5,b=0.75. Hybrid fuses full rule and BM25 ranks
        using RRF(k=60), then applies fixed preference/season rules. All methods
        exclude stock<=0. A deterministic item_id tie-breaker is shared.
        """
        if method not in METHODS:
            raise ValueError("unknown retrieval method")
        if not isinstance(k, int) or isinstance(k, bool) or k < 1:
            raise ValueError("k must be a positive integer")
        if as_of != "2026-06-15":
            raise ValueError("retrieval uses the fixed canonical scenario date")
        context = ranking_context(user)
        eligible = {iid for iid, item in self.items.items() if item.get("stock", 0) > 0}
        rule = self._rule_scores(context)
        if method == "rule":
            return sorted(eligible, key=lambda iid: (-rule[iid], iid))[:k]
        lexical = self._bm25_scores(context)
        if method == "bm25":
            return sorted(eligible, key=lambda iid: (-lexical[iid], iid))[:k]
        scores = Counter()
        for source in (rule, lexical):
            for position, iid in enumerate(sorted(eligible, key=lambda x: (-source[x], x)), 1):
                scores[iid] += 1 / (60 + position)
        for iid in eligible:
            item = self.items[iid]
            scores[iid] += 0.001 * (item.get("category_l1") in context["preferred_categories"])
            # June in the frozen scenario: fixed product-fact seasonal rule.
            scores[iid] += 0.001 * (item.get("suit_season") in ("全季", "四季", "夏季"))
        return sorted(eligible, key=lambda iid: (-scores[iid], iid))[:k]


class PairwiseReranker:
    """Linear pairwise logistic scorer; no LLM, IDs, or cart input at inference.

    Training cart IDs supply weak positive labels only. Fixed-seed negatives are
    uniformly sampled in-stock non-cart products. Features use only sanitized
    preferences/search plus product text and fixed-June season facts. Reranking
    is restricted to the hybrid top-50 candidate pool. No holdout tuning occurs.
    """

    def __init__(self, index: RetrievalIndex):
        self.index = index
        self.weights = None
        self.training_report: dict = {}

    def feature_vectors(self, user: dict) -> dict[str, list[float]]:
        context = ranking_context(user)
        query_tokens = set(tokenize(build_query(context)))
        lexical = self.index._bm25_scores(context)
        maximum = max(lexical.values(), default=0.0) or 1.0
        terms = context["last_search_terms"]
        denominator = max(1, len(terms))
        vectors = {}
        for iid, item in self.index.items.items():
            title = str(item.get("title", ""))
            category = " ".join(str(item.get(key, "")) for key in ("category_l1", "category_l2", "category_l3"))
            category_tokens, title_tokens = set(tokenize(category)), set(tokenize(title))
            vectors[iid] = [float(item.get("category_l1") in context["preferred_categories"]),
                            sum(term in title for term in terms) / denominator,
                            sum(term in category for term in terms) / denominator, lexical[iid] / maximum,
                            len(query_tokens & category_tokens) / max(1, len(query_tokens)),
                            len(query_tokens & title_tokens) / max(1, len(query_tokens)),
                            float(item.get("suit_season") in ("全季", "四季", "夏季"))]
        return vectors

    def fit(self, tasks: list[dict], users: dict[str, dict], *, iterations: int = 2000,
            learning_rate: float = 0.1, l2: float = 0.01, negatives_per_positive: int = 8, seed: int = PAIRWISE_SEED) -> dict:
        """Fit only dev tasks, rejecting any holdout rather than filtering it."""
        import numpy as np
        if any(task.get("split") != "dev" for task in tasks):
            raise ValueError("pairwise fit accepts development tasks only; holdout is forbidden")
        if iterations < 1 or learning_rate <= 0 or l2 < 0 or negatives_per_positive < 1:
            raise ValueError("invalid pairwise training parameters")
        rng = random.Random(seed)
        eligible = sorted(iid for iid, item in self.index.items.items() if item.get("stock", 0) > 0)
        differences, used_users, used_tasks, pair_ids = [], set(), set(), []
        positive_count = 0
        seen_users = set()
        cpu_start, wall_start = time.process_time(), time.perf_counter()
        for task in sorted(tasks, key=lambda row: row["task_id"]):
            uid = task["user_id"]
            if uid in seen_users:
                continue
            seen_users.add(uid)
            user = users.get(uid)
            if user is None:
                continue
            cart = set(user.get("recent_cart_item_ids", []))
            positives = sorted(cart & set(eligible))
            negatives = [iid for iid in eligible if iid not in cart]
            if not positives or not negatives:
                continue
            features = self.feature_vectors(ranking_context(user))
            used_users.add(uid)
            used_tasks.add(task["task_id"])
            positive_count += len(positives)
            for positive in positives:
                for negative in rng.sample(negatives, min(negatives_per_positive, len(negatives))):
                    differences.append([a - b for a, b in zip(features[positive], features[negative])])
                    pair_ids.append([uid, positive, negative])
        if not differences:
            raise ValueError("no development cart positive/negative pairs")
        matrix = np.asarray(differences, dtype=np.float64)
        weights = np.zeros(len(PAIRWISE_FEATURES), dtype=np.float64)
        def loss() -> float:
            return float(np.logaddexp(0.0, -np.einsum("ij,j->i", matrix, weights)).mean() + 0.5 * l2 * np.square(weights).sum())
        before = loss()
        for _ in range(iterations):
            # Tiny feature matrix: avoid spawning a multithread BLAS pool.
            logits = np.clip(np.einsum("ij,j->i", matrix, weights), -50.0, 50.0)
            gradient = -np.einsum("ij,i->j", matrix, 1.0 / (1.0 + np.exp(logits))) / len(matrix) + l2 * weights
            weights -= learning_rate * gradient
        after = loss()
        if not np.isfinite(weights).all() or not math.isfinite(after):
            raise ValueError("nonfinite pairwise training")
        self.weights = tuple(float(value) for value in weights)
        self.training_report = {"method": "linear_pairwise_logistic_with_L2", "label_source": "synthetic_development_cart_weak_labels",
                                "training_split": "dev", "training_user_count": len(used_users), "training_user_ids": sorted(used_users),
                                "training_task_ids": sorted(used_tasks), "positive_count": positive_count, "negative_pair_count": len(differences),
                                "negative_sampling": "uniform in-stock non-cart products without replacement per positive",
                                "pair_ids_sha256": hashlib.sha256(json.dumps(pair_ids, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
                                "seed": seed, "iterations": iterations, "learning_rate": learning_rate, "l2": l2,
                                "negatives_per_positive": negatives_per_positive, "feature_names": list(PAIRWISE_FEATURES),
                                "weights": list(self.weights), "loss_before": before, "loss_after": after,
                                "cpu_seconds": time.process_time() - cpu_start, "wall_seconds": time.perf_counter() - wall_start,
                                "candidate_generator": "hybrid", "candidate_pool_size": 50, "holdout_used_for_fit_or_tuning": False}
        return self.training_report

    def scores(self, user: dict) -> dict[str, float]:
        if self.weights is None:
            raise ValueError("pairwise reranker has not been fitted")
        return {iid: sum(weight * value for weight, value in zip(self.weights, features))
                for iid, features in self.feature_vectors(ranking_context(user)).items()}

    def rank(self, user: dict, *, k: int = 10, as_of: str = "2026-06-15") -> list[str]:
        candidates = self.index.rank("hybrid", ranking_context(user), k=50, as_of=as_of)
        scores = self.scores(ranking_context(user))
        return sorted(candidates, key=lambda iid: (-scores[iid], iid))[:k]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dataset_provenance(tasks: list[dict], manifest_path: Path | None) -> dict:
    task_bytes = (json.dumps(tasks, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    task_hash = hashlib.sha256(task_bytes).hexdigest()
    result = {"tasks_sha256": task_hash, "manifest_checked": False,
              "source_sha256": {name: _sha(ROOT / name) for name in ("data/raw/users.csv", "data/raw/items.csv", "data/recommendation_feedback_history.csv")}}
    if manifest_path and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest.get("artifacts", {}).get("tasks.json", {}).get("sha256")
        if expected and expected != task_hash:
            raise ValueError("tasks differ from the frozen dataset manifest")
        for name, digest in manifest.get("source_sha256", {}).items():
            if _sha(ROOT / name) != digest:
                raise ValueError(f"canonical source differs from frozen manifest: {name}")
        result.update({"manifest_checked": True, "manifest_path": str(manifest_path), "manifest_sha256": _sha(manifest_path),
                       "manifest_includes_source_hashes": bool(manifest.get("source_sha256"))})
    return result


def run_evaluation(output_dir: str | Path, *, tasks: list[dict] | None = None, manifest_path: str | Path | None = None, include_learned: bool = False) -> dict:
    """Evaluate user-disjoint splits; optional learning fits development only.

    Unknown users and users without a label are disclosed in coverage counts;
    absent labels are excluded from metric means rather than scored as zero.
    Fault-injection scenarios identify the frozen task users only: this is a
    retrieval ablation, not a test of fault recovery in the Agent loop.
    """
    tasks = build_tasks() if tasks is None else tasks
    by_split: dict[str, set[str]] = {}
    for task in tasks:
        by_split.setdefault(task["split"], set()).add(task["user_id"])
    split_names = sorted(by_split)
    if any(by_split[a] & by_split[b] for index, a in enumerate(split_names) for b in split_names[index + 1:]):
        raise ValueError("user IDs leak between task splits")
    provenance = _dataset_provenance(tasks, Path(manifest_path) if manifest_path else None)
    users, items = load_canonical_users(), load_canonical_items()
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    index = RetrievalIndex(items)
    build_cpu = time.process_time() - cpu_start
    build_wall = time.perf_counter() - wall_start
    methods = METHODS + ((LEARNED_METHOD,) if include_learned else ())
    learned = PairwiseReranker(index) if include_learned else None
    if learned:
        learned.fit([task for task in tasks if task["split"] == "dev"], users)
        holdout_users = {task["user_id"] for task in tasks if task["split"] == "holdout"}
        if holdout_users & set(learned.training_report["training_user_ids"]):
            raise ValueError("holdout user entered pairwise training")
    rows = []
    for task in tasks:
        user = users.get(task["user_id"])
        targets = weak_labels(user or {}, items)
        for method in methods:
            cpu_start, wall_start = time.process_time(), time.perf_counter()
            if user:
                ranked = (learned.rank(ranking_context(user), as_of=task.get("as_of", "2026-06-15")) if method == LEARNED_METHOD
                          else index.rank(method, ranking_context(user), as_of=task.get("as_of", "2026-06-15")))
            else:
                ranked = []
            cpu_elapsed, wall_elapsed = time.process_time() - cpu_start, time.perf_counter() - wall_start
            for source in LABEL_SOURCES:
                labels = targets[source]
                rows.append({"task_id": task["task_id"], "user_id": task["user_id"], "split": task["split"], "scenario": task["scenario"],
                             "known_user": user is not None, "method": method, "label_source": source, "query": build_query(user or {}),
                             "label_count": len(labels), "unavailable_label_count": sum(items[iid]["stock"] <= 0 for iid in labels),
                             "label_item_ids": sorted(labels), "ranked_item_ids": ranked,
                             **ranking_metrics(ranked, labels), "cpu_seconds": cpu_elapsed, "wall_seconds": wall_elapsed})
    summary = []
    for split in split_names:
        for source in LABEL_SOURCES:
            for method in methods:
                group = [row for row in rows if row["split"] == split and row["label_source"] == source and row["method"] == method]
                labeled = [row for row in group if row["label_count"]]
                known = [row for row in group if row["known_user"]]
                summary.append({"split": split, "method": method, "label_source": source, "task_count": len(group),
                                "known_user_count": len(known), "evaluated_user_count": len(labeled), "unlabeled_user_count": len(group) - len(labeled),
                                "label_coverage_all": len(labeled) / len(group) if group else 0.0,
                                "label_coverage_known": len(labeled) / len(known) if known else 0.0,
                                **{key: statistics.fmean(row[key] for row in labeled) if labeled else None for key in ("recall_at_10", "mrr_at_10", "ndcg_at_10")},
                                "unavailable_label_count": sum(row["unavailable_label_count"] for row in labeled),
                                "mean_cpu_ms": 1000 * statistics.fmean(row["cpu_seconds"] for row in known) if known else None,
                                "mean_wall_ms": 1000 * statistics.fmean(row["wall_seconds"] for row in known) if known else None})
    report = {"schema_version": "rec-agent-retrieval-ablation-v1", "canonical_version": CANONICAL_SCHEMA_VERSION, "catalog_size": len(items),
              "eligible_catalog_size": sum(item["stock"] > 0 for item in items.values()), "k": 10,
              "ranking_user_fields": ["preferred_categories", "last_search_terms"], "primary_label_source": "cart",
              "method_parameters": {"rule": {"preferred_category_weight": 4, "search_title_weight": 3},
                                    "bm25": {"k1": 1.5, "b": 0.75, "tokenizer": "Chinese bigram and Latin word frequency"},
                                    "hybrid": {"fusion": "RRF", "rrf_k": 60, "preferred_category_bonus": 0.001, "season_bonus": 0.001, "reranker": "deterministic product-fact rules"}},
              "limitations": ["Synthetic 200-item catalog; method validation only, not online improvement.",
                               "Cart membership is a weak behavior target, not human relevance gold.",
                               "Exact search labels derive from the query and measure lexical recovery only.",
                               "No vector retrieval, embedding calls, or LLM preference optimization.",
                               "Unavailable target items remain in recall denominator; all rankers filter unavailable items.",
                               "Unlabeled users are excluded from metric averages; user splits remain disjoint."],
              "provenance": provenance, "index_build_cpu_seconds": build_cpu, "index_build_wall_seconds": build_wall,
              "summary": summary, "per_task": rows}
    if learned:
        report["schema_version"] = "rec-agent-retrieval-ablation-v2-pairwise"
        report["pairwise_training"] = learned.training_report
        report["method_parameters"][LEARNED_METHOD] = {"reranker": "dev-only weakly supervised linear pairwise logistic", "candidate_generator": "hybrid", "candidate_pool_size": 50}
        report["limitations"].extend(["Learned pairwise is a small CPU linear model, not LLM or human-preference training.",
                                       "Development cart metrics reuse fitting labels and are training-set diagnostics; holdout is the user-disjoint evaluation.",
                                       "Hyperparameters were fixed for this learned run; existing baseline holdout results had already been inspected, so this is not a newly blinded test set."])
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if learned:
        (directory / "pairwise_model.json").write_text(json.dumps(learned.training_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, records in (("summary.csv", summary), ("per_task.csv", rows)):
        with (directory / name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]) if records else [])
            writer.writeheader()
            writer.writerows({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in record.items()} for record in records)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dataset-manifest", default="runs/agent-benchmark-v1/dataset/manifest.json")
    parser.add_argument("--learned", action="store_true", help="fit a dev-cart pairwise reranker; keep holdout excluded from fitting")
    args = parser.parse_args()
    report = run_evaluation(args.output_dir, manifest_path=args.dataset_manifest, include_learned=args.learned)
    print(json.dumps({"output_dir": args.output_dir, "catalog_size": report["catalog_size"], "summary": report["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
