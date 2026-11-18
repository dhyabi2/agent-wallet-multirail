# Changelog

## Unreleased (after 0.1.0)

Not released yet: `pyproject.toml` still says 0.1.0. The behaviour below
differs from 0.1.0 for `swap.py` callers, so the release that ships it needs a
new version.

### Changed

- `NanswapProvider` uses the plain endpoints with a ticker that names the
  chain (`USDC-BASE`). `from_network` is joined into the ticker; `to_network`
  is accepted and echoed on `SwapEstimate` but not sent.
- `NANSWAP_*_PARTNER` constants still import but now alias the plain paths
  (`/create-order`, ...), not the partner endpoints. A hand-built partner
  request posted to them goes to `/create-order` with the wrong body.
- With the default transport, `estimate`/`limits`/`order`/`create_order` raise
  `SwapRefused` instead of `urllib.error.HTTPError`/`URLError`. Every such
  refusal is also a `urllib.error.URLError` (and an `OSError`), so
  `except URLError` still catches it; read `exc.reason`, not `exc.code`.
  That includes `order_unconfirmed` from `create_order` when an HTTP failure
  caused it. Refusals the module raises on its own (`no_api_key`,
  `invalid_api_key`, `invalid_swap_pair`, an order's refused terms, a refusal
  read back from `order_log`) are plain `SwapRefused`.
- Patching `urllib.request.urlopen` still intercepts the default transport:
  it is looked up per request and a replaced one is called instead of the
  network. `agent_wallet_multirail.swap._open` is the narrower patch point.
- An API key containing whitespace or a non-visible-ASCII character (a
  trailing newline) is refused `invalid_api_key` before anything is sent; the
  `order_key` stays free and the key never appears in a message or
  `order_log`. 0.1.0 raised `http.client`'s `ValueError`, which quoted it.
- `nanswap_ticker` (now in `__all__`) refuses a currency or network that is
  not alphanumeric (`invalid_swap_pair`).
- On `create_order`, an exception a custom transport raises is wrapped:
  `order_unconfirmed`, or `provider_unreachable` when it proves nothing was
  sent; the original is the `__cause__`.
- A retry of a recorded `order_key` no longer reads `limits` first; limits
  only bound a new order.
- Redirects are never followed. A 3xx on the create-order POST is
  `order_unconfirmed`, and the `nanswap-api-key` header is never sent to the
  redirect target.
- A create-order whose outcome is unknown (3xx, 5xx, timeout, unreadable
  reply, an error reply carrying an order id at any status, or an exception
  from a custom provider that cannot be classified) leaves the `order_key`
  recorded as `order_unconfirmed`; 0.1.0 created the order again on retry.

### Added

- `release_pending_order_key(order_log, order_key)`: frees a key left
  `order_unconfirmed` once the provider shows no order. Refuses
  `order_key_not_releasable` for a key holding a created order or a send.
