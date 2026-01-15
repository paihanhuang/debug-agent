---
description: SDLC V-Model workflow for code changes
---

# SDLC V-Model Workflow

Follow this workflow for ALL code changes. The V-Model pairs each development phase with a corresponding testing phase.

## Left Side (Development Phases)

### 1. Requirements Analysis
- [ ] Define what the change should accomplish
- [ ] Identify acceptance criteria
- [ ] Document user-facing requirements in `implementation_plan.md`

### 2. System Design  
- [ ] Define high-level architecture changes
- [ ] Identify affected components/modules
- [ ] Document system design decisions

### 3. Architecture Design
- [ ] Define module interfaces
- [ ] Document integration points
- [ ] Create/update module diagrams

### 4. Module Design
- [ ] Define class/function signatures
- [ ] Document data structures
- [ ] Specify internal logic

### 5. Implementation
- [ ] Write the code
- [ ] Follow coding standards
- [ ] Add inline documentation

---

## Right Side (Testing Phases)

### 6. Unit Testing
- [ ] Write unit tests for each module
- [ ] Test edge cases
- [ ] Achieve minimum 80% coverage
// turbo
- [ ] Run: `python -m pytest tests/ -v`

### 7. Integration Testing
- [ ] Test module interactions
- [ ] Verify interfaces work correctly
- [ ] Test with realistic data

### 8. System Testing
- [ ] End-to-end testing
- [ ] Test full pipeline with real inputs
// turbo
- [ ] Run: `python -m src.main --help`

### 9. Acceptance Testing
- [ ] Verify requirements are met
- [ ] User review of output
- [ ] Document in `walkthrough.md`

---

## Traceability Matrix

| Requirement | Design | Implementation | Unit Test | Integration Test | System Test |
|-------------|--------|----------------|-----------|------------------|-------------|
| REQ-1       | DES-1  | src/module.py  | test_module.py | test_integration.py | test_e2e.py |

---

## Checklist Before Merge

- [ ] All requirements documented
- [ ] Design reviewed
- [ ] Code implemented
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] System tests pass
- [ ] Acceptance criteria verified
- [ ] walkthrough.md updated
