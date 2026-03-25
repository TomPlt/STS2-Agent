# STS2 Performance Optimization Opportunities

## Code-Level Analysis

### Hot Path Bottlenecks (Identified)

1. **Game Data Lookup Performance** (server.py:640-698)
   - `_lookup_game_data_item()` does 3x case-sensitive lookups per query
   - `get_relevant_game_data()` calls `sts2.get_state()` unconditionally to detect scene
   - Suggestion: Cache case-normalized keys, pass scene context instead of re-fetching

2. **State Extraction Overhead** (server.py:403-426)
   - `_agent_state()`, `_extract_agent_view()`, `_compact_act_response()` all iterate dicts to strip nulls
   - Dict comprehensions are fast but called on every tool invocation
   - Suggestion: Pre-build filtered structure on mod side if possible

3. **Scene Detection** (server.py:392-400)
   - `_detect_scene_from_screen()` uses multiple `any()` checks per call
   - Could be compiled to single string check or dict lookup
   - Suggestion: Use frozenset for keyword checks or single regex

4. **Action Signature Building** (server.py:497-507)
   - `_wait_until_actionable_impl()` builds signature strings repeatedly in polling loop
   - Joins sorted action names on each iteration
   - Suggestion: Compute baseline once, use hash-based comparison

5. **No Connection Pooling** (client.py)
   - Every HTTP request creates a new connection to the game API
   - Suggestion: Use persistent connection pool (requests.Session)

6. **JSON Parsing Per Tool** (server.py)
   - `play_sequence()` parses JSON (line 809)
   - Every MCP tool result gets JSON serialized
   - Suggestion: Minimal - already using FastMCP efficiently

## Network/Architecture Bottlenecks

7. **State Polling in Fallback** (server.py:494-507)
   - Fallback poll interval default is 250ms
   - Environment: `STS2_MCP_FALLBACK_POLL_SECONDS`
   - Suggestion: Configurable via env; consider adaptive backoff

8. **Game API Latency** (unknown without live measurements)
   - HTTP request-response cycle for each action
   - Potential for request batching already exists (`play_sequence()`)
   - Suggestion: Profile live to measure

## Estimated Impact

| Optimization | Complexity | Estimated Speedup |
|---|---|---|
| Connection pooling | Low | 5-15% (HTTP overhead) |
| Case-normalization caching | Low | 10-20% (data lookups) |
| Scene detection optimization | Low | 5-10% (string operations) |
| State filtering optimization | Medium | 5-10% (dict ops) |
| Signature building optimization | Low | 2-5% (polling loop) |
| Reduce game state calls | Medium | 5-15% (eliminates redundant API calls) |

## Recommended Next Steps

1. **Measure first**: Profile with live game instance to identify actual bottlenecks
2. **Quick wins**: Connection pooling + case normalization (highest ROI, lowest complexity)
3. **Mid-term**: State filtering optimization + signature caching
4. **Long-term**: Architectural changes (state caching, request batching)

## Notes

- Code is well-structured and relatively efficient already
- Main gains come from reducing network calls and improving data lookup performance
- No obvious algorithmic inefficiencies
- Profiling needed to confirm where real bottlenecks are in your specific use case
