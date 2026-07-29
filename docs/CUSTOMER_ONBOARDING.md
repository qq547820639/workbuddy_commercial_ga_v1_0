# Customer Onboarding

## State machine

```text
DISCOVERY
→ CONFIGURATION
→ SHADOW
→ AGENT_DRAFT
→ LIVE_SEND
→ COMPLETED
```

A project can advance only one stage at a time.

## Mandatory controls

### Configuration

- business owner assigned;
- data inventory completed;
- approval matrix approved.

### Shadow

- expert teams published;
- Skills published;
- mailboxes connected;
- security review completed.

### Agent Draft

- Gate B ready;
- required shadow days completed.

### Live Send

- Gate C ready;
- owner training completed;
- support ready.

### Completed

- Gate D ready;
- Production Open;
- operational handover complete;
- tenant exit explained.

The API rejects stage skipping and incomplete control lists.
