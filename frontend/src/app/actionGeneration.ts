export type ActionToken = Readonly<{ userId: string; generation: number }>

export class ActionGeneration {
  private userId: string
  private generation = 0

  constructor(userId: string) { this.userId = userId }

  update(userId: string) {
    if (this.userId === userId) return
    this.userId = userId
    this.generation += 1
  }

  invalidate() {
    this.userId = ''
    this.generation += 1
  }

  capture(): ActionToken { return Object.freeze({ userId: this.userId, generation: this.generation }) }

  isCurrent(token: ActionToken): boolean { return token.userId === this.userId && token.generation === this.generation }
}
