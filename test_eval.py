import asyncio
from life_os.agent.graph import app as agent_app
from life_os.evals.metrics import slot_fill_f1

async def test_case(input_text, exp):
    predicted = {}
    async for step in agent_app.astream(
        {"raw_input": input_text, "user_id": "eval_user"},
        stream_mode="updates",
        config={"configurable": {"thread_id": "eval_test_" + input_text[:10]}},
    ):
        if "extract" in step and "entities" in step["extract"]:
            predicted = step["extract"]["entities"]
            break  # Break after extraction
            
    # process prediction dumps
    if hasattr(predicted, "model_dump"):
        predicted = predicted.model_dump(exclude_unset=True, exclude_none=True)
    elif isinstance(predicted, dict):
        for k, v in predicted.items():
            if hasattr(v, "model_dump"):
                predicted[k] = v.model_dump(exclude_unset=True, exclude_none=True)
            elif isinstance(v, list):
                predicted[k] = [
                    i.model_dump(exclude_unset=True, exclude_none=True) if hasattr(i, "model_dump") else i
                    for i in v
                ]
    
    predicted = {k: v for k, v in predicted.items() if k in exp}
    print("-------")
    print("INPUT:", input_text)
    print("PRED:", predicted)
    print("EXP:", exp)
    print("F1:", slot_fill_f1(predicted, exp).f1)

async def main():
    await test_case("woke up at 7 but cant remember when i slept", {'sleep': {'wake_hour': 7, 'wake_minute': 0}})
    await test_case("remind me to call the dentist tomorrow", {'tasks': [{'task': 'call the dentist'}]})

asyncio.run(main())
