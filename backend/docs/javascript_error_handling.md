# JavaScript Error Handling Basics

## try and catch
Put code that might fail inside a `try` block. If an error is thrown, JavaScript jumps to the `catch` block.

```javascript
try {
  const data = JSON.parse(text);
} catch (error) {
  console.error("Bad JSON:", error.message);
}
```

## Checking the error type
A `catch` block catches every error. To react to only one kind, check it with `instanceof`, like `error instanceof TypeError`, and throw the others again.

## finally
The `finally` block always runs after try and catch, so it is the right place for cleanup such as hiding a loading spinner.

## Throwing your own errors
Use `throw new Error("message")` to signal a problem. You can make custom error classes with `class MyError extends Error`. To keep the original cause, write `new Error("Could not load profile", { cause: error })`.

## Async code
With `async` and `await`, wrap the awaited call in try and catch. A promise that fails and has no catch handler causes an unhandled rejection, which can crash a Node.js program.

## Common errors
- TypeError: a value has the wrong type, such as reading a property of undefined.
- ReferenceError: a variable is not defined.
- SyntaxError: the code or JSON text is not valid.
- RangeError: a number is outside the allowed range.

## Avoiding TypeError
Use optional chaining, written as `user?.address?.city`, so a missing value gives undefined instead of an error.
