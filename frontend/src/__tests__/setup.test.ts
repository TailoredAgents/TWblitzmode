describe('Jest Setup', () => {
  test('should be able to run tests', () => {
    expect(true).toBe(true)
  })

  test('should have access to jest-dom matchers', () => {
    const element = document.createElement('div')
    element.textContent = 'Hello World'
    document.body.appendChild(element)

    expect(element).toBeInTheDocument()
    expect(element).toHaveTextContent('Hello World')

    document.body.removeChild(element)
  })

  test('should mock Next.js router', () => {
    const { useRouter } = require('next/navigation')
    const router = useRouter()

    expect(router.push).toBeDefined()
    expect(typeof router.push).toBe('function')
  })
})