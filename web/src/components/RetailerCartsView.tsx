import type { RetailerCart } from '../api'
import { formatRetailerName } from '../format'

interface RetailerCartsViewProps {
  carts: Record<string, RetailerCart>
  onChoose?: (choice: 'shufersal' | 'rami_levy' | 'decline') => void
  chosenRetailer?: string | null
}

function CartCard({
  retailer,
  cart,
  onChoose,
  chosen,
}: {
  retailer: string
  cart: RetailerCart
  onChoose?: (choice: 'shufersal' | 'rami_levy' | 'decline') => void
  chosen: boolean
}) {
  return (
    <div className={`cart-card${chosen ? ' cart-card--chosen' : ''}`}>
      <h3>{formatRetailerName(retailer)}</h3>

      <table className="cart-items">
        <thead>
          <tr>
            <th>Item</th>
            <th>Qty</th>
            <th>Subtotal</th>
          </tr>
        </thead>
        <tbody>
          {cart.items.map((line) => (
            <tr key={line.item_code}>
              <td>{line.product_name}</td>
              <td>{line.qty}</td>
              <td>{line.subtotal.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="cart-total">Total: {cart.total.toFixed(2)}</p>

      {cart.budget != null && (
        <p className={cart.over_budget_by != null ? 'budget-exceeded' : 'budget-ok'}>
          {cart.over_budget_by != null
            ? `Over budget by ${cart.over_budget_by.toFixed(2)}`
            : 'Within budget'}
        </p>
      )}

      {cart.savings_vs_other != null && cart.savings_vs_other > 0 && (
        <p className="cart-savings">Saves {cart.savings_vs_other.toFixed(2)} vs. the other retailer</p>
      )}

      {cart.missing_items.length > 0 && (
        <div className="missing-items">
          <strong>Missing:</strong>{' '}
          {cart.missing_items.map((item) => String(item.name)).join(', ')}
        </div>
      )}

      {cart.trade_off_suggestions.length > 0 && (
        <ul className="trade-off-suggestions">
          {cart.trade_off_suggestions.map((s, i) => (
            <li key={i}>
              Swap {String(s.current_choice)} for {String(s.suggested_choice)} to save{' '}
              {Number(s.savings).toFixed(2)}
            </li>
          ))}
        </ul>
      )}

      {onChoose && (
        <button type="button" onClick={() => onChoose(retailer as 'shufersal' | 'rami_levy')}>
          Choose {formatRetailerName(retailer)}
        </button>
      )}
    </div>
  )
}

export function RetailerCartsView({ carts, onChoose, chosenRetailer }: RetailerCartsViewProps) {
  return (
    <div className="retailer-carts">
      <div className="retailer-carts-grid">
        {Object.entries(carts).map(([retailer, cart]) => (
          <CartCard
            key={retailer}
            retailer={retailer}
            cart={cart}
            onChoose={onChoose}
            chosen={chosenRetailer === retailer}
          />
        ))}
      </div>
      {onChoose && (
        <button type="button" className="decline-button" onClick={() => onChoose('decline')}>
          Neither — just show me this
        </button>
      )}
    </div>
  )
}
