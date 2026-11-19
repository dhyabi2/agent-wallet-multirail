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
  read back from `order_log`) are plain `SwapRefused`, and so are
  `provider_refused` for an error body that came with HTTP 200 and
  `provider_response_unrecognised` for a JSON reply missing a field or of
  the wrong type (an HTTP 4xx/5xx `provider_refused` is a `URLError`).
- A bare `TimeoutError`, `ConnectionResetError`, `http.client.HTTPException`
  (`IncompleteRead`, `RemoteDisconnected`), `json.JSONDecodeError` or
  `UnicodeDecodeError` that 0.1.0 let through from the default transport is
  now a `SwapRefused`/`URLError` that is also an instance of that original
  class (`ValueError` for `UnicodeDecodeError`), so `except TimeoutError` /
  `except ValueError` / `except http.client.HTTPException` still catch it;
  the original is the `__cause__`. `order_unconfirmed` caused by one keeps
  the same class.
- The default transport parses JSON with `parse_float=str`: a JSON number
  is kept as its exact wire text, so `SwapOrder.raw` and the `raw` recorded
  in `order_log` hold such numbers as strings (0.1.0: floats). JSON
  integers stay `int`.
- An opener installed with `urllib.request.install_opener` is honoured, as
  in 0.1.0: its handlers (a fake `https_open`, a CA, a proxy, auth) carry
  the request, with redirects still never followed; the installed opener
  is not modified.
- A provider error reply quoting the API key (HTTP 200 or an error status,
  however long the body) has the key redacted from `str(exc)`, `.message`
  and `order_log`.
- An amount string past Python's 4300-digit `int()` limit is refused
  (`invalid_amount` or `provider_response_unrecognised`) instead of raising
  `ValueError`; in a create-order reply the order is then recorded under the
  `order_key` with its id.
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

- `order_network_unconfirmed`: a create-order reply whose `from` names a
  ticker other than the planned one (`USDC-BASE` on a `USDC-BSC` plan) is
  refused and never funded; the order is recorded under the `order_key`, so
  a retry creates no second one. A reply with no `from` is read.

- `release_pending_order_key(order_log, order_key)`: frees a key left
  `order_unconfirmed` once the provider shows no order. Refuses
  `order_key_not_releasable` for a key holding a created order or a send.
