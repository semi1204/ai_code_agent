"""todos: a per-session task list."""

import uuid

from tools.base import tool


@tool(
    "todos",
    "Track tasks for this session. action: add (content) | complete (id) | list | clear.",
    {"action": "string", "id": "string?", "content": "string?"},
    kind="memory",
)
def todos(args, s):
    action = args["action"].lower()
    if action == "add":
        if not args.get("content"):
            return "error: content is required for add"
        todo_id = uuid.uuid4().hex[:8]
        s.todos[todo_id] = args["content"]
        return f"Added todo [{todo_id}]: {args['content']}"
    if action == "complete":
        if args.get("id") not in s.todos:
            return f"error: todo not found: {args.get('id')}"
        return f"Completed todo [{args['id']}]: {s.todos.pop(args['id'])}"
    if action == "list":
        return "\n".join(f"[{todo_id}] {content}" for todo_id, content in s.todos.items()) or "No todos"
    if action == "clear":
        count = len(s.todos)
        s.todos.clear()
        return f"Cleared {count} todos"
    return f"error: unknown action: {args['action']}"
