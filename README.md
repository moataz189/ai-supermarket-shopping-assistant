# AI Supermarket Shopping Assistant

An agent that turns a natural-language shopping request (grocery list or recipe) into two
independently-optimized shopping carts, one per retailer, and prepares the chosen retailer's
real cart via browser automation — stopping before checkout, login, or payment.

See [`docs/spec.md`](docs/spec.md) for the full design and [`docs/plan.md`](docs/plan.md) for
the implementation plan.

## Development

```bash
make install   # install runtime + dev dependencies
make lint      # run ruff
make test      # run pytest
make run       # run the FastAPI app locally
```
