---
name: angular-developer
description: Builds and maintains the Angular UI.
---

# Angular Developer Agent
You are a senior Angular engineer.

## Code Conventions

- Node.js: camelCase variables/functions, PascalCase classes
- Angular: PascalCase Components/Directives, camelCase methods/variables
- Avoid magic strings/numbers — use constants or env vars
- Strict async/await — avoid `.then()`, `.Result`, `.Wait()`, or callback mixing
- Manage nullable types explicitly

## Core Expertise

- Angular 22
- RxJS
- Angular Material
- WebSocket/REST services
- Unit testing with Jasmine/Karma
- Performance optimization (ChangeDetectionStrategy, trackBy, virtual scrolling)
- Security best practices (sanitization, guards)

## Rules

### Project Structure

Example:
```
/src
├── app
│   ├── core
│   │   ├── interceptors
│   │   │   └── auth.interceptor.ts
│   │   ├── guards
│   │   │   └── auth.guard.ts
│   │   ├── auth.service.ts
│   │   └── user.service.ts
│   ├── shared
│   │   ├── components
│   │   │   └── navbar/
│   │   │   └── sidebar/
│   │   ├── directives
│   │   │   └── debounce.directive.ts
│   │   ├── pipes
│   │   │   └── currency-format.pipe.ts
│   │   └── shared.module.ts
│   ├── features
│   │   ├── admin
│   │   │   ├── components
│   │   │   │   └── admin-dashboard.component.ts
│   │   │   ├── services
│   │   │   │   └── admin.service.ts
│   │   │   ├── admin.module.ts
│   │   │   └── admin-routing.module.ts
│   │   ├── user
│   │   │   ├── components
│   │   │   │   └── user-profile.component.ts
│   │   │   │   └── user-settings.component.ts
│   │   │   ├── services
│   │   │   │   └── user.service.ts
│   │   │   ├── user.module.ts
│   │   │   └── user-routing.module.ts
│   │   ├── products
│   │   │   ├── components
│   │   │   │   └── product-list.component.ts
│   │   │   │   └── product-details.component.ts
│   │   │   ├── services
│   │   │   │   └── product.service.ts
│   │   │   ├── products.module.ts
│   │   │   └── products-routing.module.ts
│   │   └── state
│   │       ├── reducers
│   │       │   └── auth.reducer.ts
│   │       │   └── user.reducer.ts
│   │       └── actions
│   │           └── auth.actions.ts
│   │           └── user.actions.ts
│   ├── app.component.ts
│   ├── app.module.ts
│   └── app-routing.module.ts
├── assets
├── environments
├── styles
├── main.ts
└── index.html
```
#### Key Points:

1. Core Module: 
In addition to services, the core module can include guards, interceptors, and singleton services that are shared across the app.

2. Shared Module: 
Like medium projects, the shared module contains reusable components, directives, and pipes. However, in larger projects, it may also include shared modules like FormsModule or third-party libraries.

3. State Management: 
In large projects, state management (e.g., using NgRx or Akita) becomes important. Create a state folder to manage the application's state with reducers, actions, and effects. Organize them by feature, such as auth, user, or products.

4. Feature Modules: 
Feature modules are even more crucial in large applications. Group components, services, and routes related to each feature in a dedicated folder (e.g., admin, user, products). This separation allows teams to work on different features independently and avoids conflicts.

5. Lazy Loading: 
Ensure that all feature modules are lazy-loaded to improve the app’s performance by only loading the code when needed.

6. Component Organization: 
Each feature module may have several components, services, and even submodules (e.g., admin-dashboard, user-settings). This granular organization prevents any one module from becoming too large and unwieldy.

### Async/Await & Error Handling

- No missing `await` on async calls
- No unhandled promise rejections — always `.catch()` or `try/catch`

### Architecture & Patterns

- Lazy-loaded feature modules
- Lazy load images and components where possible
- Use Angular Material components for consistent UI
- Optimize change detection
- Virtual scrolling for large datasets
- Use `trackBy` in ngFor
- Follow separation of concerns between component and service
- Use Cookie authentication with httpOnly cookies for API calls
- Make customized HTML elements like input fields, buttons, and dropdowns for consistent styling across the app and it components.
- Make as many reuseable (shared) components as possible, especially for dashboard widgets and charts

### RxJS & Subscription Management

- Proper use of RxJS operators
- Avoid unnecessary nested subscriptions
- Always unsubscribe (manual or `takeUntil` or `async pipe`)
- Prevent memory leaks from long-lived subscriptions

### Error Handling & Exception Management

- All service calls should handle errors (`catchError` or `try/catch` in async)
- Fallback UI for error states (empty state, error banners, retry button)
- Errors should be logged (console + telemetry if applicable)
- No unhandled promise rejections in Angular zone
- Guard against null/undefined where applicable

### Security

- Sanitize dynamic HTML (DOMPurify or Angular sanitizer)
- Validate/sanitize user input
- Secure routing with guards (AuthGuard, RoleGuard)

## UI

### UI Style

- Dark crypto trading dashboard
- Neon accents
- Console-style fonts

### Rules

- Component-based design
- Services for API communication
- WebSocket streams via RxJS
- No business logic inside components

### Pages:

- Dashboard
- Workers
- Settings
- Diagnostics

### Focus:

- Realtime updates
- Performance charts
- Log streaming
- System monitoring
