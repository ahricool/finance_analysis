import { describe, expect, it } from 'vitest'
import { buttonVariants } from '..'

describe('buttonVariants', () => {
  it('uses the pink brand color for the default primary button', () => {
    const classes = buttonVariants()

    expect(classes).toContain('bg-brand')
    expect(classes).toContain('text-brand-foreground')
    expect(classes).not.toContain('bg-primary')
  })
})
