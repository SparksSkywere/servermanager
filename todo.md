# Code Cleanup TODO: Refactor Entire Project

**Objective**: Clean up all files in the workspace to remove redundant code, improve performance, and make the code look less AI-generated, while fully maintaining existing functionality. Do not introduce new features or break any logic.

**Steps to Execute**:
1. **Scan for Redundancy**:
   - Identify and remove unused variables, functions, imports, and dead code across all files.
   - Merge duplicate logic into shared utilities where appropriate.

2. **Optimize Performance**:
   - Profile hotspots: Replace inefficient algorithms (e.g., nested loops with maps/sets).
   - Reduce unnecessary computations, I/O, or API calls.
   - Add memoization or caching for repeated operations.
   - Ensure optimizations are measurable (e.g., aim for 20%+ speed gains without complexity).

3. **De-AI-ify Code**:
   - Refactor verbose or generic patterns to be more concise and idiomatic (e.g., use language-specific best practices).
   - Vary naming conventions for natural flow (avoid repetitive prefixes like 'ai_').
   - Remove excessive comments; keep only those explaining "why" not "what".
   - Apply design patterns (e.g., SOLID) to improve structure without altering behavior.

4. **Multi-File Handling**:
   - Process all files in the workspace, starting with core modules.
   - Ensure cross-file references (e.g., imports) remain intact.

5. **Validation**:
   - Preview changes and confirm no functionality breaks.
   - Suggest running tests post-refactor.

**Constraints**:
- Preserve all current features and outputs.
- Prioritize readability over extreme optimization.
- Language: [Specify your language, e.g., JavaScript/Python].
- Output: Provide diffs for review before applying.

Execute this plan step-by-step using multi-file context.