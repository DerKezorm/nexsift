import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { Button } from './ui'

/** What Chrome's translator does: each text node is replaced by <font><font>…</font></font>. */
function translateLikeChrome(root: Node) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const texts: Text[] = []
  while (walker.nextNode()) texts.push(walker.currentNode as Text)
  for (const text of texts) {
    const outer = document.createElement('font')
    const inner = document.createElement('font')
    inner.textContent = text.data
    outer.appendChild(inner)
    text.replaceWith(outer)
  }
}

// A button turned on its spinner after Chrome had translated the page, and React tried to put the spinner before a
// text node that was no longer there.
test('a translated button still shows its spinner, in front of the label', () => {
  const { rerender } = render(<Button>Send a test</Button>)
  translateLikeChrome(screen.getByRole('button'))

  rerender(<Button loading>Send a test</Button>)

  const button = screen.getByRole<HTMLButtonElement>('button')
  expect(button.firstElementChild?.matches('svg.animate-spin')).toBe(true)
  expect(button.disabled).toBe(true)
  expect(button.textContent).toBe('Send a test')

  rerender(<Button>Send a test</Button>)
  expect(screen.getByRole('button').querySelector('svg.animate-spin')).toBeNull()
})
