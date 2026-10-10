# Python Error Handling Basics

## try and except
Put code that might fail inside a `try` block. If an error happens, Python jumps to the matching `except` block.

```python
try:
    age = int(input("Age: "))
except ValueError:
    print("Please type a number.")
```

## Catch specific errors
Always name the error type you expect, like `ValueError` or `KeyError`. A bare `except:` with no type is a bad habit, because it also hides unexpected bugs and even stops you from pressing Ctrl+C.

## else and finally
The `else` block runs only when no error happened. The `finally` block runs no matter what, even if an error occurs. It is the right place to close files or connections.

## Context managers
The `with` statement closes things for you. For example, `with open("data.txt") as f:` closes the file automatically, even if an error happens inside.

## Raising your own errors
Use `raise` to signal a problem. You can make custom error classes by inheriting from `Exception`. Use `raise NewError from old_error` to keep the original cause visible.

## Logging errors
Inside an except block, call `logging.exception("message")`. It saves the message together with the full traceback.

## Common errors
- KeyError: a dictionary key does not exist.
- IndexError: a list position is out of range.
- TypeError: a value has the wrong type.
- FileNotFoundError: the file path does not exist.

## EAFP and LBYL
Python programmers often follow EAFP, which means "Easier to Ask Forgiveness than Permission": try the action and handle the error. The other style is LBYL, "Look Before You Leap": check conditions first.
