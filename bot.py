import poe

RECONNAISSANCE_PROMPT = """You are a deep research assistant. Perform an exact-match web search to identify what the user is asking about.

USER QUERY: {question}

Instructions:
- Your goal is to find the literal, exact-match result for this query
- If it's a product, find the official product page or authoritative source
- If it's a proper noun, find the definitive reference
- Summarize what you found in 2-3 sentences maximum
- Be precise - do not interpret or guess what they might mean

Begin with the exact-match result:"""

QUERY_GENERATION_PROMPT = """You are a deep research assistant. Based on the reconnaissance result, generate exactly 4 focused web search queries that would help provide comprehensive and critical coverage of the topic.

USER QUESTION: {question}

RECONNAISSANCE RESULT:
{recon_result}

Requirements for each query:
- Be specific and targeted (not generic)
- Cover different aspects/angles of the topic, including potential disagreements or contested claims
- Include queries that probe for potential misinformation or outdated information
- Include queries that verify key facts from multiple authoritative angles
- Be optimized for web search (use relevant keywords)
- Each query should be independent and answer a distinct sub-question

Output format: Return ONLY a JSON array of 4 strings, nothing else. Example:
["query 1", "query 2", "query 3", "query 4"]"""

FOLLOWUP_QUERY_PROMPT = """You are a deep research assistant analyzing search results to determine what additional queries are needed.

USER QUESTION: {question}

CURRENT SEARCH RESULTS:
{results}

Instructions:
- Review the current results and identify gaps, conflicts, or areas needing deeper investigation
- Generate exactly 5 additional search queries to address these gaps
- Prioritize queries that:
  1. Verify conflicting information across sources
  2. Probe for potential biases or outdated claims
  3. Fill in missing context or perspectives
  4. Cross-reference facts with authoritative sources
- If the current results are comprehensive and consistent, return an empty JSON array []

Output format: Return ONLY a JSON array of up to 5 additional strings, or an empty array []. Example:
["followup query 1", "followup query 2"] or []"""

SYNTHESIS_PROMPT = """You are a deep research assistant synthesizing information from multiple web searches with critical analysis.

USER QUESTION: {question}

SEARCH RESULTS (numbered):
{results}

Instructions:
1. Synthesize all results into a comprehensive, well-structured answer
2. Use markdown formatting with headers, bullet points, and paragraphs as appropriate
3. Include inline citations where you use specific information from a source, using the format [source #]
4. Critically evaluate sources - note potential biases, outdated info, or contradictions across sources
5. Explicitly flag conflicting information and note which sources are more authoritative
6. Do not accept claims at face value - note uncertainty and confidence levels where appropriate
7. Be thorough but readable - this is a deep research output, not a superficial summary
8. Highlight consensus OR disagreements across sources, and note when claims are contested

IMPORTANT: At the end of your response, add a "Sources" section in this exact format:
---
**Sources:**
[1] [query text]
[2] [query text]
[3] [query text]
...
---

Begin your synthesized response:"""

MAX_SEARCH_RESULTS_LENGTH = 8000


def extract_search_results(chat: poe.Chat) -> str:
    messages = list(chat.messages)
    for msg in reversed(messages):
        if msg.role == "bot":
            text = msg.text.strip()
            if text:
                return text[:MAX_SEARCH_RESULTS_LENGTH]
    return "No results returned."


def reconnaissance(question: str) -> str:
    with poe.default_chat.start_message() as msg:
        msg.write(f"**Step 1/5: Reconnaissance**\n\nPerforming exact-match search to identify: \"{question}\"")

    recon_chat = poe.Chat(
        poe.Message(text=RECONNAISSANCE_PROMPT.format(question=question)),
        quiet=True,
    )
    response = poe.call("Gemini-3-Flash", recon_chat)
    return response.text.strip()


def generate_related_queries(question: str, recon_result: str) -> list[str]:
    with poe.default_chat.start_message() as msg:
        msg.write("**Step 2/5: Analyzing reconnaissance result**")

    query_gen_chat = poe.Chat(
        poe.Message(text=QUERY_GENERATION_PROMPT.format(
            question=question,
            recon_result=recon_result
        )),
        quiet=True,
    )
    response = poe.call("Gemini-3-Flash", query_gen_chat)
    text = response.text.strip()

    try:
        import json
        queries = json.loads(text)
        if isinstance(queries, list):
            return [str(q) for q in queries if q]
    except Exception:
        pass

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    queries = []
    for line in lines:
        line = line.strip('"-[].,0123456789. ')
        if line and not line.startswith("#") and len(line) > 10:
            queries.append(line)
            if len(queries) == 4:
                break

    return queries[:4] if queries else []


def generate_followup_queries(question: str, current_results: list[tuple[str, str]]) -> list[str]:
    results_text = ""
    for i, (query, result) in enumerate(current_results, 1):
        results_text += f"\n--- SEARCH {i} (Query: {query}) ---\n{result}\n"

    query_gen_chat = poe.Chat(
        poe.Message(text=FOLLOWUP_QUERY_PROMPT.format(
            question=question,
            results=results_text
        )),
        quiet=True,
    )
    response = poe.call("Gemini-3-Flash", query_gen_chat)
    text = response.text.strip()

    try:
        import json
        queries = json.loads(text)
        if isinstance(queries, list):
            return [str(q) for q in queries if q]
    except Exception:
        pass

    return []


def run_parallel_searches(queries: list[str], phase: str = "") -> list[tuple[str, str]]:
    phase_label = f" {phase}" if phase else ""
    with poe.default_chat.start_message() as msg:
        msg.write(f"**Step 3{phase_label}: Launching {len(queries)} parallel web searches...**")

    def search_with_index(i: int, query: str):
        try:
            result_chat = poe.call("Web-Search", query)
            return (query, extract_search_results(result_chat))
        except Exception as e:
            return (query, f"Search failed: {str(e)}")

    tasks = [lambda i=i, q=q: search_with_index(i, q) for i, q in enumerate(queries)]
    results = poe.parallel(*tasks, return_exceptions=True)

    processed = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed.append((queries[i], f"Search failed: {str(result)}"))
        else:
            processed.append(result)

    return processed


def synthesize_results(question: str, search_results: list[tuple[str, str]]) -> str:
    with poe.default_chat.start_message() as msg:
        msg.write("**Step 5/5: Synthesizing findings into comprehensive answer...**")

    results_text = ""
    for i, (query, result) in enumerate(search_results, 1):
        results_text += f"\n--- SEARCH {i} (Query: {query}) ---\n{result}\n"

    synthesis_chat = poe.Chat(
        poe.Message(text=SYNTHESIS_PROMPT.format(
            question=question,
            results=results_text
        )),
        quiet=True,
    )
    response = poe.call("Gemini-3-Flash", synthesis_chat)
    return response.text


def main():
    question = poe.query.text
    max_total_searches = 10

    with poe.default_chat.start_message() as msg:
        msg.write("**Deep Research Mode Initialized**\n\nYour query is being researched across multiple dimensions...")

    recon_result = reconnaissance(question)

    related_queries = generate_related_queries(question, recon_result)

    all_results = [(f"EXACT: {question}", recon_result)]

    related_results = run_parallel_searches(related_queries)
    all_results.extend(related_results)

    successful_count = sum(1 for _, r in all_results if not r.startswith("Search failed"))

    if successful_count >= 3 and len(all_results) < max_total_searches:
        followup_queries = generate_followup_queries(question, all_results)

        if followup_queries:
            remaining_slots = max_total_searches - len(all_results)
            followup_queries = followup_queries[:remaining_slots]

            followup_results = run_parallel_searches(followup_queries, "2")
            all_results.extend(followup_results)

    with poe.default_chat.start_message() as msg:
        msg.write(f"**Research complete.** Synthesized {len(all_results)} sources into final answer.")

    final_answer = synthesize_results(question, all_results)

    with poe.default_chat.start_message() as msg:
        msg.write(final_answer)


if __name__ == "__main__":
    main()