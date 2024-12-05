# Standard library
import asyncio
import time
import os
from typing import Optional

# Third party
from openai import AsyncOpenAI

# Local
# from o100.optimizer.utils import (
#     crossover,
#     evaluate_fitness,
#     init_population,
#     select_parent,
#     infer_task_description
# )
# from o100.dtos import ProgressStep, PromptCandidate
from optimizer.utils import (
    crossover,
    evaluate_fitness,
    init_population,
    select_parent,
    infer_task_description,
)
from dtos import ProgressStep, PromptCandidate


async def optimize(
    prompt: str,  # First version of the prompt
    task_description: Optional[str] = None,  # Description of task prompt is used for
    population_size: int = 5,  # No. of candidates to generate per iteration
    num_iters: int = 5,  # Max. no. of population "generations"
    num_elites: int = 2,  # No. of top candidates to pass onto the next generation
    threshold: float = 1.0,
    api_key: str = "",
):
    openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", api_key))
    start_time = time.time()

    best_candidate = initial_prompt = PromptCandidate(prompt)
    task_description, token_count = await infer_task_description(
        prompt, task_description, openai
    )

    yield ProgressStep(
        index=0,
        value=0.125,
        message="Starting optimization",
        best_prompt=prompt,
        token_count=token_count,
        start_time=start_time,
    )

    population, _token_count = await init_population(
        prompt, task_description, population_size, openai
    )
    token_count += _token_count
    num_prompts = 0

    yield ProgressStep(
        index=0,
        value=0.25,
        message="Starting optimization",
        best_prompt=best_candidate.prompt,
        token_count=token_count,
        start_time=start_time,
    )

    tasks = [
        evaluate_fitness(candidate, task_description, initial_prompt, openai)
        for candidate in population
    ]
    for index, task in enumerate(asyncio.as_completed(tasks)):
        candidate, _token_count = await task
        token_count += _token_count
        num_prompts += 1

        if candidate.prompt == best_candidate.prompt:
            best_candidate = candidate
            initial_prompt = candidate

        yield ProgressStep(
            index=0,
            value=0.25 + (0.75 * (index + 1) / len(tasks)),
            message="Starting optimization",
            best_prompt=best_candidate.prompt,
            best_score=best_candidate.fitness,
            token_count=token_count,
            num_prompts=num_prompts,
            start_time=start_time,
            end_time=time.time() if index == len(tasks) - 1 else None,
        )

    for index in range(num_iters):
        start_time = time.time()
        yield ProgressStep(
            index=index + 1,
            value=0.0,
            message=f"Iteration #{index + 1}/{num_iters}",
            best_prompt=best_candidate.prompt,
            best_score=best_candidate.fitness,
            token_count=token_count,
            num_prompts=num_prompts,
            start_time=start_time,
        )

        # Evaluate fitness of each candidate
        tasks = [
            evaluate_fitness(candidate, task_description, initial_prompt, openai)
            for candidate in population
        ]
        for i, task in enumerate(asyncio.as_completed(tasks)):
            _, _token_count = await task
            token_count += _token_count
            num_prompts += 1

            yield ProgressStep(
                index=index + 1,
                value=0.25 * ((i + 1) / len(tasks)),
                message=f"Iteration {index + 1}/{num_iters}",
                best_prompt=best_candidate.prompt,
                best_score=best_candidate.fitness,
                token_count=token_count,
                num_prompts=num_prompts,
                start_time=start_time,
            )

        # Sort population by fitness
        population.sort(key=lambda candidate: candidate.fitness, reverse=True)

        # Update the best individual
        generation_best = population[0]
        if (
            not best_candidate.fitness
            or generation_best.fitness > best_candidate.fitness
        ):
            best_candidate = generation_best

        # Terminate if a candidate meets the fitness threshold
        if best_candidate.fitness >= threshold:
            yield ProgressStep(
                index=index + 1,
                value=1.0,
                message=f"Iteration {index + 1}/{num_iters}",
                best_prompt=best_candidate.prompt,
                best_score=best_candidate.fitness,
                token_count=token_count,
                num_prompts=num_prompts,
                start_time=start_time,
                end_time=time.time(),
            )
            break

        # Generate the new population
        mates = (
            (select_parent(population), select_parent(population))
            for _ in range(population_size - num_elites)
        )
        tasks = [
            crossover(*parents, task_description=task_description, openai=openai)
            for parents in mates
        ]
        children = []
        for i, task in enumerate(asyncio.as_completed(tasks)):
            child, _token_count = await task
            token_count += _token_count

            yield ProgressStep(
                index=index + 1,
                value=0.25 + ((i + 1) / len(tasks)) * 0.75,
                message=f"Iteration {index + 1}/{num_iters}",
                best_prompt=best_candidate.prompt,
                best_score=best_candidate.fitness,
                token_count=token_count,
                num_prompts=num_prompts,
                start_time=start_time,
                end_time=time.time() if i == len(tasks) - 1 else None,
            )
            children.append(child)

        population = population[:num_elites] + children

    yield ProgressStep(
        index=index + 2,
        message="Optimization complete! 🧬",
        best_prompt=best_candidate.prompt,
        best_score=best_candidate.fitness,
        token_count=token_count,
        num_prompts=num_prompts,
        is_terminal=True,
    )
