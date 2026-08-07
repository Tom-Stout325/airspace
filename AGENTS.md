# AirSpace Development Instructions

## Project purpose

AirSpace is a Django application for professional drone pilots to manage pilot information, aircraft, operations planning, FAA approvals, authorization workflows, CONOPS generation, and related documentation.

AirSpace is a general-purpose drone operations platform.

Never assume or introduce racing, NHRA, motorsports, broadcast television, event coverage, mapping, inspection, photography, or any other mission type unless that context was explicitly provided by the user or is already stored in the operation data.

Do not infer operational facts that are not present in the application's source data.

## Technology stack

- Python 3.12.x
- Django 5.2.x
- PostgreSQL
- Server-rendered Django templates
- Bootstrap-based responsive UI
- django-environ for environment configuration
- django-storages / S3 where configured
- WeasyPrint for PDF generation

Use Django 5.2 documentation and established Django conventions when implementing application behavior.

Prefer built-in Django functionality over unnecessary third-party packages or custom abstractions.

Do not introduce Django REST Framework, a SPA framework, or another major architectural dependency unless specifically requested.

## Application architecture

Primary Django apps currently include:

- `accounts` — authentication, users, invitations, registration
- `pilot` — pilot profiles and pilot-related information
- `drones` — user aircraft inventory and safety profiles
- `airspace` — operations planning, approvals, FAA workflows, CONOPS, airport data, geographic services, and PDFs

Respect existing app boundaries unless there is a clear architectural reason to change them.

Do not move or rename models, URLs, templates, services, or apps merely for stylistic cleanup while implementing an unrelated task.

## User ownership and data isolation

AirSpace uses a shared PostgreSQL database with application-enforced per-user ownership.

User data isolation is a critical security requirement.

Every view, form, queryset, download endpoint, child-resource lookup, service, and API endpoint involving user-owned data must ensure the data belongs to the authenticated user.

Never rely on an object ID alone when retrieving user-owned objects.

Prefer patterns such as:

`get_object_or_404(Model, pk=pk, user=request.user)`

or querying a child object through an already owner-scoped parent.

User-owned data includes, but is not limited to:

- Pilot profiles
- Drones
- Operations
- Operation aircraft assignments
- Approval applications
- CONOPS content
- Uploaded maps
- Certificates
- Logos
- Generated documents
- Flight-related records

Shared reference data such as airports, approval types, and drone safety profiles may intentionally be global.

When adding forms containing model choices, restrict choices to objects the current user is authorized to use.

Do not introduce cross-user access through autocomplete endpoints, downloads, PDFs, forms, admin-like interfaces, or indirect relationships.

Remember that `bulk_create()`, queryset `update()`, raw SQL, and similar operations may bypass model validation.

## Django models and migrations

All schema changes must use Django migrations.

Do not edit an existing applied migration to change current schema behavior unless specifically instructed.

Create a new migration for new schema changes.

Preserve database constraints and add constraints where they materially improve integrity.

Use `settings.AUTH_USER_MODEL` for user relationships.

Be cautious with PostgreSQL-specific behavior because the project intentionally uses PostgreSQL features including `ArrayField`.

Do not replace PostgreSQL-specific fields merely to make the application database-agnostic.

## Views and forms

Prefer standard Django patterns.

Keep authorization checks explicit and easy to audit.

Use forms and model forms for validation rather than putting all validation logic into templates or JavaScript.

Pass required context into forms, especially `request.user`, parent objects, or operation context when validation or queryset filtering depends on it.

Avoid catching broad exceptions that hide programming errors.

Return useful validation errors to the user instead of allowing database integrity errors to become 500 responses.

## Templates and UI

AirSpace is mobile-first.

Every UI change must work well on phone-sized screens first and then progressively improve for tablet and desktop layouts.

Use the project's existing Bootstrap patterns and visual language.

Avoid fixed-width layouts that cause horizontal scrolling on mobile devices.

Forms should have:

- Clear labels
- Useful helper text
- Appropriate input types
- Accessible validation feedback
- Logical grouping
- Touch-friendly controls

Do not unnecessarily redesign unrelated pages while implementing a feature.

The primary layout is `templates/index.html` with `templates/navbar.html`.

Respect the logo and static image conventions documented in `static/images/README.md`.

## File uploads and private documents

Treat user-uploaded operational documents as private unless the product explicitly defines them as public.

Do not expose sensitive user uploads by directly rendering unrestricted storage URLs when an authenticated owner-scoped download view is more appropriate.

This includes:

- FAA certificates
- Company logos where appropriate
- Operation maps
- Approval documents
- Operational documents
- Other user-specific uploads

Validate uploaded files appropriately for the feature being implemented.

Do not assume that an object storage URL is private merely because the application page containing it requires authentication.

## FAA and regulatory content

FAA-related functionality requires especially strict source fidelity.

Do not invent:

- FAA requirements
- ATC instructions
- ATC frequencies
- ATC phone numbers
- UASFM altitudes
- Waiver provisions
- Authorization conditions
- Regulatory relief
- Operational necessity
- Mission purpose
- Crew qualifications
- Aircraft capabilities
- Safety mitigations
- Procedures that the user did not provide

Distinguish between:

- User-entered planning information
- Application-generated recommendations
- Verified regulatory requirements
- Conditions contained in an actual FAA authorization or waiver

Never present user-entered ATC coordination information as though the FAA or ATC required it unless that requirement is supported by authoritative source data.

Do not imply that obstacle sensing, LiDAR, geofencing, Return-to-Home, or similar aircraft features provide separation from crewed aircraft.

Do not imply authorization for operations over people, moving vehicles, controlled airspace, BVLOS, night operations, or any other regulated activity unless the applicable authority is explicitly established.

FAA/CONOPS text must be factually grounded in operation data.

If required information is missing, clearly identify it as missing rather than fabricating a plausible value.

## CONOPS generation

AirSpace currently contains both deterministic and AI-assisted CONOPS generation.

When changing CONOPS behavior:

- Inspect both generation paths.
- Keep regulatory wording consistent where appropriate.
- Preserve source-fidelity guardrails.
- Do not silently add facts not contained in operation data.
- Do not silently change regulatory interpretations.
- Add or update tests for important generated language.
- Consider stale/generated-content behavior when source operation data changes.
- Preserve the distinction between generated drafts and user-reviewed/finalized content.

Changes to AI prompts should be treated as application behavior changes and reviewed accordingly.

## External services

The application may interact with services such as:

- OpenAI
- OpenStreetMap / Nominatim
- AWS S3
- Email services

Do not make unnecessary external network calls in tests.

Mock external services where appropriate.

Handle service errors without exposing secrets or raw internal errors to users.

Respect service usage policies, rate limits, and attribution requirements.

## Secrets and configuration

Never commit:

- `.env`
- API keys
- passwords
- secret keys
- database credentials
- AWS credentials
- private certificates
- access tokens

Use environment variables and `.env.example` for safe configuration documentation.

Production configuration should fail safely when required secrets are absent.

Do not hard-code production secrets or credentials as fallbacks.

## Static and media files

Do not commit generated collected static files, uploaded media, caches, archives, or virtual environments.

Do not automatically delete files that are already tracked merely because they now match `.gitignore`.

Treat cleanup of historically tracked artifacts as a separate deliberate task.

Maintain filename case consistently because production storage may be case-sensitive.

## Testing requirements

Every functional change should include appropriate tests unless there is a clear reason testing is impractical.

At minimum, test:

- Successful behavior
- Authentication requirements
- Ownership/isolation where user-owned objects are involved
- Invalid input
- Important workflow constraints
- Regression behavior related to the change

For security-sensitive user-owned resources, include a test proving one user cannot access another user's object.

Use the project environment when available:

`./venv/bin/python manage.py test`

Run the narrowest relevant test set during development, then broader tests before completing substantial changes.

Also run:

`./venv/bin/python manage.py check`

when appropriate.

Do not modify production data merely to run tests.

## Change discipline

Before modifying code:

1. Inspect the relevant models, views, forms, URLs, templates, services, and tests.
2. Understand the existing workflow.
3. Check `git status`.
4. Account for existing uncommitted work before editing overlapping files.

While implementing:

- Make the smallest cohesive change that satisfies the request.
- Avoid unrelated refactoring.
- Preserve backwards compatibility where reasonable.
- Do not silently remove existing functionality.
- Do not overwrite user-created content without explicit intent.
- Do not use destructive Git commands unless specifically requested.

After implementing:

1. Review the diff.
2. Run `git diff --check`.
3. Run relevant tests.
4. Run broader tests when warranted.
5. Report exactly what changed.
6. Report tests run and their results.
7. Report any migrations created.
8. Report unresolved risks or follow-up work.

Do not commit or push unless explicitly requested.

## Git practices

Never:

- Force push unless explicitly instructed.
- Rewrite history without explicit instruction.
- Discard unrelated working-tree changes.
- Stage unrelated files.
- Commit secrets.
- Commit generated patch bundles or temporary installer artifacts unless specifically required.

Keep commits focused on one logical change.

Before committing, show or inspect the staged diff and confirm unrelated files are excluded.

## Code quality

Prefer clear, maintainable Python over clever abstractions.

Follow existing project conventions.

Use descriptive names.

Keep functions focused.

Add comments when they explain non-obvious business or regulatory reasoning; do not add comments that merely restate the code.

Avoid duplicated business rules when a clear shared implementation already exists.

Do not perform large architectural rewrites as part of a small feature request.

## Documentation

Update documentation when behavior, configuration, setup, or operational assumptions materially change.

Do not preserve obsolete patch-installation documentation after a patch has been incorporated into normal source control.

Treat `scripts/scripts.txt` as informal working notes, not authoritative project documentation.

## User working notes

`scripts/scripts.txt` is the user's personal, intentionally modified working-notes file.

Unless the user explicitly requests otherwise:

- Ignore its modified Git status.
- Do not inspect its contents as part of routine repository analysis.
- Do not modify it.
- Do not restore or revert it.
- Do not stage it.
- Do not commit it.
- Do not include it in unrelated diffs or cleanup work.
- Do not report its modified status as an error, concern, dirty-working-tree problem, or blocker.
- Its presence as a modified tracked file does not mean the repository is unsafe for normal development work.

Only interact with `scripts/scripts.txt` when the user explicitly asks you to work with that file.

## When uncertain

If a requested implementation could:

- Weaken user isolation
- Change FAA or regulatory meaning
- Expose private documents
- Delete user data
- Alter production infrastructure
- Require a major architectural change

stop and clearly explain the issue before taking the risky action.

Prefer asking for a decision over silently making a consequential assumption.
