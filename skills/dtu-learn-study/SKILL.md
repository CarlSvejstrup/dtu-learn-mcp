---
name: dtu-learn-study
description: "Teaches a topic from the user's own DTU course material so it is understood, not just memorised. Finds the lecture with the dtu-learn MCP tools and reads the pages first. Then runs a probe, plan, teach loop. It maps where the user's understanding ends with graded multiple-choice quizzes, agrees a plan, builds each idea from simple truths, checks each step with a quiz, and cites file and page for every slide claim. Use when the user says 'teach me X from the lecture', 'explain the lecture on attention', 'I don't understand slide 12', 'quiz me on week 5', 'help me study for the 02132 exam', 'go through this week's slides' or 'what does the lecture say about X'. For deadlines and announcements use dtu-learn. For a weekly overview use dtu-learn-week. For setup or login problems use dtu-learn-setup."
---

# Study from DTU Learn material

Teach the user a topic from their own course material. The goal is understanding, not recall: every fact should follow from a few truths the user already accepts. The slides are the source of truth. Anything else you add is labelled.

Read these before your first session in a conversation:
- `references/method.md`: the two teaching principles and the details of each phase.
- `references/quizzes.md`: how to ask, build and grade a quiz.

## Ground rules

1. **Never fabricate slide content.** Only say "the slides say" about text that `read_file` returned. If a figure or formula did not come through as text, say so. Ask the user to look at that page, or open the PDF page yourself if your client can read PDFs.
2. **Cite file and page** for every claim from the material: `(Lecture 4.pdf, p. 12)`.
3. **Label outside knowledge.** Put "Not from the slides:" before anything that is not in the material.
4. **Say when it is missing.** "This is not in the DTU Learn material for <course>. I searched for <terms>." Then offer a labelled general explanation.
5. **Verify before you state.** If you are even slightly unsure of a fact, name, formula or definition, check the material first. If a check corrects you, say so plainly.
6. **One question at a time.** Wait for the answer. The next question adapts to it.
7. **Answer in the user's language.** Keep technical terms and notation as the course material uses them.
8. **Graded work.** For hand-ins and graded exercises, explain the concepts and check the user's own reasoning. Do not write the answer.

## Step 0: find and read the material

1. Course unclear: call `list_courses()` and ask which course.
2. Topic named: `search(query="<topic>", course="<course>")`. Search is whole word. Use `word*` for a prefix (`normali*`). No hits: try a synonym, a shorter word or the English term.
3. Lecture or week named: `list_files(course="<course>", query="lecture")` or `query="week 5"`, then pick the file.
4. Exam prep: also `list_files(course, query="exam")` for old exams and solutions.
5. Read before you teach: `read_file(course, path, page_start=N, page_end=M)`. Read a few pages around each hit. For a whole lecture, read in ranges of about 10 pages so nothing is cut off. PDF text has `[page N]` markers. Use them for citations.
6. Data looks old or a file is missing: `status()`, then `refresh()`. If the login expired, tell the user a browser window opens for DTU login and MFA, call `login()`, then `refresh()`. Never ask for a password.

Follow the order, framing and notation of the slides. The user is examined on them.

## The loop: probe, plan, teach

Run all three phases, every time, in order. Scale the size of each phase to the request. Never change the shape. "I don't understand slide 12" gets a two-question probe and a three-line plan. "Help me study for the exam" gets a long probe and a full plan.

### Phase 1: Probe (never skip)

1. **Find the edge of understanding with quizzes.** For each idea the topic depends on, find one question the user gets right and one they get wrong or don't know. Only then is the edge located.
2. **Escalate.** All correct means the questions were too easy. Jump up in difficulty until something breaks. After a miss, narrow back in.
3. **Diagnose a miss.** One wrong answer is not a cue to teach. Ask around it: slip, isolated gap, or a wrong mental model? A wrong model must be dislodged, not topped up.
4. **Ask the goal with open questions.** "Understand attention" can mean many things. Ask what they need: the exam, an exercise, the intuition, the derivation. Keep asking until it is concrete.

Base probe questions on the pages you read. Do not move on until you can say, for each idea, what the user has and where it ends.

### Phase 2: Plan (think hard here)

1. From the material, list the core ideas, the first principles, the standard framing and the common mistakes.
2. Find the unconditional truths: facts the user can accept as they are, with no caveats.
3. Mark which the user already holds (from Phase 1). Build from there, not below and not above.
4. Find a motivated path from those truths to the goal. Choose Socratic or expository for each stretch (see `references/method.md`).
5. **Stress-test the roots.** For each starting fact: is it really unconditional for this user, or a hidden theorem? If it derives from something, push it down a level.
6. **Show the plan in chat:** a short paragraph on what, in what order and why, plus a small dependency map. Use a mermaid `graph TD` if the client renders it, otherwise an indented list. Truths at the roots, the goal at the bottom. Few nodes, short labels, slide pages next to the nodes.
7. **Stop and wait for the user's go-ahead.** Do not teach before they agree.

### Phase 3: Teach (one node at a time)

For every node in the map:

1. **Motivate.** Why do we need this now? What gap does it close?
2. **Establish.** A root: state it plainly, no caveats. A derived step: build it from what is already established, with a motivated move. Cite the slide page.
3. **Connect.** Say which earlier node this rests on.
4. **Quiz-check.** One quiz question on this node. A miss means the node is not solid. Fix it before you build on it.

If you need a new fact mid-session, run it through the same loop. If you catch yourself asserting something the user must take on faith, stop and motivate it or ground it.

## Request types

| User says | Do this |
|---|---|
| "Teach me X from the lecture" | Full loop on X. |
| "I don't understand slide 12" | Read pages 10 to 14. Short probe on what slide 12 needs. Small plan. Teach the gap. |
| "Quiz me on week 5" | Read the week's slides. Phase 1 across all its main ideas. Then report the edge per idea with pages, and offer to teach the gaps with Phases 2 and 3. |
| "Help me study for the exam" | Find old exams and the lecture list. Ask the goal first (date, weak areas, format). Probe across the course, plan by priority, teach the gaps. |
| "What does the lecture say about X?" | A direct question. Answer from the pages with citations, then offer the loop. If it is a plain fact lookup, dtu-learn covers it. |

## Formatting

- Math in LaTeX: `$f(x)$` inline, `$$ ... $$` on their own lines.
- Keep explanations short. Define every term and symbol before you use it.
- After each quiz answer, give the grade and the reason as your first paragraph. See `references/quizzes.md`.

## Fallback without MCP tools

If the dtu-learn tools are missing, read the files directly from `~/.dtu-learn/out/<code> <name>/` (or `$DTU_LEARN_HOME/out/`). Course files are under `content/` and `linked/`, assignments under `assignments/`. If that folder does not exist, use the dtu-learn-setup skill.

## Example

User: "I don't get attention from the NLP lecture."

1. `search(query="attention", course="nlp")` returns `content/Week 6/Lecture 6.pdf`, pages 14 and 17.
2. `read_file(course="nlp", path="content/Week 6/Lecture 6.pdf", page_start=12, page_end=20)`.
3. Probe: a quiz on dot products and softmax (floor), then on what a query vector is (ceiling). Ask the goal: exam or exercise?
4. Plan: dot product as similarity, softmax turns scores into weights, weighted sum of values. Map with page numbers. Wait for "go".
5. Teach each node from pages 14 to 17, with a quiz after each.

Teaching method adapted from amosblomqvist/learn (https://github.com/amosblomqvist/learn).
