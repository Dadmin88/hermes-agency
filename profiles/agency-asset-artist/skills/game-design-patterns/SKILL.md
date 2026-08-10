---
name: game-design-patterns
description: Game loops, state machines, entity systems, and procedural generation
tags: [design, game-design, patterns, mechanics, systems]
---

# Game Design Patterns

## When to Use
When designing game mechanics, building game systems, or solving game architecture problems.

## Prerequisites
- Understanding of the game genre and target platform
- Knowledge of the game engine (Godot, Unity, etc.)

## Steps

### Step 1: Design the game loop
```
Core Loop (what the player does every 30 seconds):
  Explore → Encounter → Resolve → Reward

Meta Loop (what the player does every session):
  Plan → Execute → Progress → Unlock

Compulsion Loop (keeps players engaged):
  Action → Variable Reward → Investment → Repeat
```

### Step 2: Implement state machines
```gdscript
# Godot GDScript example
enum State { IDLE, WALKING, ATTACKING, HURT, DEAD }
var current_state = State.IDLE

func _process(delta):
    match current_state:
        State.IDLE:
            if input_vector != Vector2.ZERO:
                change_state(State.WALKING)
        State.WALKING:
            move(delta)
            if attack_input:
                change_state(State.ATTACKING)
        State.ATTACKING:
            play_attack_animation()
```

### Step 3: Balance game systems
- **Difficulty curve**: Gradual increase, punctuated by plateaus
- **Economy**: Earn rate vs spend rate, inflation control
- **Progression**: Linear vs exponential, meaningful choices
- **Risk/Reward**: Higher risk = higher reward

### Step 4: Design for flow
- Clear goals at every moment
- Immediate feedback on actions
- Challenge matches skill level
- No interruptions during gameplay
- Sense of control and agency

### Step 5: Playtest and iterate
- Watch players without helping them
- Note where they get confused, frustrated, or bored
- Measure: time to first death, completion rate, session length
- Iterate based on data, not assumptions

## Tool Usage
- `write_file` for design documents
- `read_file` for reviewing game code

## Pitfalls
1. Don't design in a vacuum — playtest early and often
2. Don't add complexity without depth — each system should matter
3. Don't ignore the first 30 seconds — that's when players decide to stay
4. Don't balance by spreadsheet alone — feel matters more than math
5. Don't copy other games — understand why their patterns work

## Quick Reference
Core Loop: Explore → Encounter → Resolve → Reward
State Machine: Define states, transitions, and behaviors
Balance: Difficulty curve, economy, risk/reward
Flow: Clear goals, immediate feedback, matched challenge
Playtest: Watch, measure, iterate