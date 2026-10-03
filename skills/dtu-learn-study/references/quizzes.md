# Quizzes

A question with a right answer is a quiz. A question without one (goal, preference, what next) is an open question. Keep them apart.

## How to ask

If your client has a multiple-choice question tool (AskUserQuestion in Claude Code), use it. Otherwise write the question in chat with options A to D and wait for the reply.

- **Open question:** normal use. You may mark a recommended option.
- **Quiz:** follow the protocol below exactly.

## Quiz protocol

1. **Decide the correct option before you ask.** Reveal nothing in the question. Never mark it "(Recommended)". Never put it first by habit. Rotate its position across quizzes.
2. **3 or 4 options**, built with the procedure below. One question per message, so the next one can adapt. Allow several picks only when several options are correct and the user must pick all.
3. **Label it as a quiz** (header "Quiz" in a question tool). Add to the question: "Answer 'don't know' if you don't know." In a question tool, tell the user to pick Other and type it. An honest "don't know" is a signal, never a wrong guess.
4. **Ground it in the material.** Base the question on a page you read. Keep math short enough to read raw if the client cannot render LaTeX.
5. **Give feedback first.** After the answer, your very first paragraph is the grade and nothing else comes before it. Start with "Correct.", "Wrong, the answer is X." or, for "don't know", "The answer is X." Then 1 to 3 sentences of why, with the slide page. Then a blank line, then continue. Always give feedback before the next quiz.

## Building the options

Do not check for evenness afterwards. Build the options so evenness is automatic.

1. **Every option is a bare claim.** No justification in any option. The biggest giveaway is a correct option that carries its own reasoning while the others are bare. All reasoning goes in your feedback.
2. **Write the correct claim first, then mutate it.** For each distractor, take one specific misconception or easily confused neighbour and state what someone holding it would claim. Use the same skeleton, length and register.
3. **Each distractor is a real error** the user might make, so the pick tells you something. Yet it is clearly wrong.
4. **No uneven emphasis.** Same length, same detail. Descriptions on all options or on none.

Read the finished set cold. If you can tell which is right without knowing the material, rebuild it.
