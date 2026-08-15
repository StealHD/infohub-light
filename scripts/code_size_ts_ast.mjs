#!/usr/bin/env node

import fs from "node:fs"
import path from "node:path"
import { pathToFileURL } from "node:url"

const [rootArgument, ...relativePaths] = process.argv.slice(2)
if (!rootArgument) {
  process.stderr.write("usage: code_size_ts_ast.mjs ROOT FILE...\n")
  process.exit(2)
}

const root = path.resolve(rootArgument)
const dependencyRoot = path.resolve(process.env.INTELISCOPE_TYPESCRIPT_ROOT || root)
const typescriptPath = path.join(dependencyRoot, "frontend", "node_modules", "typescript", "lib", "typescript.js")
if (!fs.existsSync(typescriptPath)) {
  process.stderr.write("TypeScript compiler not found; run npm --prefix frontend ci\n")
  process.exit(2)
}

const imported = await import(pathToFileURL(typescriptPath).href)
const ts = imported.default ?? imported
const containerCalls = new Set(["describe", "suite"])
const callableKinds = new Set([
  ts.SyntaxKind.ArrowFunction,
  ts.SyntaxKind.Constructor,
  ts.SyntaxKind.FunctionDeclaration,
  ts.SyntaxKind.FunctionExpression,
  ts.SyntaxKind.GetAccessor,
  ts.SyntaxKind.MethodDeclaration,
  ts.SyntaxKind.SetAccessor,
])

function scriptKind(relative) {
  if (relative.endsWith(".tsx")) return ts.ScriptKind.TSX
  if (relative.endsWith(".jsx")) return ts.ScriptKind.JSX
  if (relative.endsWith(".js") || relative.endsWith(".mjs") || relative.endsWith(".cjs")) {
    return ts.ScriptKind.JS
  }
  return ts.ScriptKind.TS
}

function propertyName(node, source) {
  if (!node) return null
  if (ts.isIdentifier(node) || ts.isPrivateIdentifier(node)) return node.text
  if (ts.isStringLiteral(node) || ts.isNumericLiteral(node)) return node.text
  return node.getText(source).replace(/\s+/g, " ").slice(0, 80)
}

function callName(expression, source) {
  if (ts.isIdentifier(expression)) return expression.text
  if (ts.isPropertyAccessExpression(expression)) return propertyName(expression.name, source)
  return expression.getText(source).replace(/\s+/g, " ").slice(0, 80)
}

function callTitle(call, source) {
  const first = call.arguments[0]
  if (first && (ts.isStringLiteral(first) || ts.isNoSubstitutionTemplateLiteral(first))) {
    return first.text.replace(/\s+/g, " ").slice(0, 100)
  }
  return null
}

function containerCall(node, source) {
  const parent = node.parent
  if (!parent || !ts.isCallExpression(parent) || !parent.arguments.includes(node)) return null
  const name = callName(parent.expression, source)
  return containerCalls.has(name) ? parent : null
}

function assignedName(node, source) {
  const parent = node.parent
  if (parent && ts.isVariableDeclaration(parent) && parent.initializer === node) {
    return propertyName(parent.name, source)
  }
  if (parent && ts.isPropertyAssignment(parent) && parent.initializer === node) {
    return propertyName(parent.name, source)
  }
  return null
}

function callableName(node, source, ordinal) {
  if (ts.isConstructorDeclaration(node)) return "constructor"
  if (node.name) return propertyName(node.name, source)
  const assigned = assignedName(node, source)
  if (assigned) return assigned
  const parent = node.parent
  if (parent && ts.isCallExpression(parent)) {
    const name = callName(parent.expression, source)
    const title = callTitle(parent, source)
    return title ? `${name}:${title}` : `${name}:callback#${ordinal}`
  }
  return `anonymous#${ordinal}`
}

function rangeStart(node) {
  const parent = node.parent
  if (parent && ts.isVariableDeclaration(parent) && parent.initializer === node) return parent
  if (parent && ts.isPropertyAssignment(parent) && parent.initializer === node) return parent
  return node
}

function controlDepthIncrement(node) {
  return ts.isIfStatement(node)
    || ts.isForStatement(node)
    || ts.isForInStatement(node)
    || ts.isForOfStatement(node)
    || ts.isWhileStatement(node)
    || ts.isDoStatement(node)
    || ts.isSwitchStatement(node)
    || ts.isCatchClause(node)
    || ts.isConditionalExpression(node)
}

function complexityIncrement(node) {
  if (controlDepthIncrement(node)) return 1
  if (ts.isCaseClause(node)) return 1
  if (ts.isBinaryExpression(node)) {
    const kind = node.operatorToken.kind
    if (
      kind === ts.SyntaxKind.AmpersandAmpersandToken
      || kind === ts.SyntaxKind.BarBarToken
      || kind === ts.SyntaxKind.QuestionQuestionToken
    ) return 1
  }
  return 0
}

function callableShape(rootNode) {
  let complexity = 1
  let maxNesting = 0

  function visit(node, depth) {
    if (node !== rootNode && callableKinds.has(node.kind)) return
    const incrementDepth = controlDepthIncrement(node) ? 1 : 0
    const nextDepth = depth + incrementDepth
    complexity += node === rootNode ? 0 : complexityIncrement(node)
    maxNesting = Math.max(maxNesting, nextDepth)
    ts.forEachChild(node, (child) => visit(child, nextDepth))
  }

  ts.forEachChild(rootNode, (child) => visit(child, 0))
  return { complexity, max_nesting: maxNesting }
}

function parseFile(relative) {
  const absolute = path.join(root, relative)
  const content = fs.readFileSync(absolute, "utf8")
  const source = ts.createSourceFile(
    relative,
    content,
    ts.ScriptTarget.Latest,
    true,
    scriptKind(relative),
  )
  if (source.parseDiagnostics.length) {
    const message = ts.flattenDiagnosticMessageText(source.parseDiagnostics[0].messageText, " ")
    throw new Error(`${relative}: TypeScript parse failed: ${message}`)
  }

  const records = []
  const names = []
  const containerNames = []
  let ordinal = 0

  function visit(node) {
    if (ts.isClassDeclaration(node) || ts.isClassExpression(node)) {
      names.push(node.name?.text ?? "anonymous-class")
      ts.forEachChild(node, visit)
      names.pop()
      return
    }
    const container = callableKinds.has(node.kind) ? containerCall(node, source) : null
    if (container) {
      const title = callTitle(container, source) ?? "anonymous"
      containerNames.push(`${callName(container.expression, source)}:${title}`)
      ts.forEachChild(node, visit)
      containerNames.pop()
      return
    }

    if (callableKinds.has(node.kind)) {
      ordinal += 1
      const name = callableName(node, source, ordinal)
      const symbol = [...containerNames, ...names, name].join(".")
      const start = source.getLineAndCharacterOfPosition(rangeStart(node).getStart(source)).line + 1
      const end = source.getLineAndCharacterOfPosition(node.end).line + 1
      records.push({
        path: relative,
        symbol,
        lines: end - start + 1,
        ...callableShape(node),
      })
      names.push(name)
      ts.forEachChild(node, visit)
      names.pop()
      return
    }
    ts.forEachChild(node, visit)
  }

  visit(source)
  return records
}

try {
  const output = relativePaths.flatMap(parseFile)
  process.stdout.write(`${JSON.stringify(output)}\n`)
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`)
  process.exit(1)
}
