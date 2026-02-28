"""CLI eval runner — run with: uv run python -m life_os.evals.run_evals"""

import asyncio
import json
from pathlib import Path

from life_os.agent.graph import app as agent_app
from life_os.evals.metrics import slot_fill_f1

PASS_THRESHOLD_F1 = 0.80  # Fail CI if below this


async def run_extraction_evals() -> dict[str, float]:
    """Run all extraction eval cases, return aggregate metrics.

    Returns:
        Dict with overall_f1, precision, recall, pass_rate.
    """
    dataset = Path("src/life_os/evals/datasets/extraction.jsonl")
    cases = [json.loads(line) for line in dataset.read_text().splitlines()]

    results = []
    for case in cases:
        predicted = {}
        async for step in agent_app.astream(
            {"raw_input": case["input"], "user_id": "eval_user"},
            config={"configurable": {"thread_id": f"eval_{case['id']}"}},
        ):
            if "extract" in step and "entities" in step["extract"]:
                predicted = step["extract"]["entities"]

        # the model returns Pydantic objects, so convert predicted to dict
        if hasattr(predicted, "model_dump"):
            predicted = predicted.model_dump(exclude_unset=True, exclude_none=True)
        elif isinstance(predicted, dict):
            # Check if inner things are models
            for k, v in predicted.items():
                if hasattr(v, "model_dump"):
                    predicted[k] = v.model_dump(exclude_unset=True, exclude_none=True)
                elif isinstance(v, list):
                    predicted[k] = [
                        (
                            i.model_dump(exclude_unset=True, exclude_none=True)
                            if hasattr(i, "model_dump")
                            else i
                        )
                        for i in v
                    ]

        # Filter predicted to only keys that exist in expected
        # to avoid penalizing bonus context (e.g. journal_note)
        predicted = {k: v for k, v in predicted.items() if k in case["expected"]}

        metrics = slot_fill_f1(predicted, case["expected"])
        results.append(metrics.f1)
        print(f"  {case['id']} EXP : {case['expected']}")
        print(f"  {case['id']}: F1={metrics.f1:.3f} | fields={metrics.field_accuracy}")

    overall_f1 = sum(results) / len(results)
    pass_rate = sum(1 for r in results if r >= PASS_THRESHOLD_F1) / len(results)
    print(f"\nOverall F1: {overall_f1:.3f} | Pass rate: {pass_rate:.1%}")

    assert (
        overall_f1 >= PASS_THRESHOLD_F1
    ), f"Extraction F1 {overall_f1:.3f} below threshold {PASS_THRESHOLD_F1}"
    return {"overall_f1": overall_f1, "pass_rate": pass_rate}


if __name__ == "__main__":
    asyncio.run(run_extraction_evals())
