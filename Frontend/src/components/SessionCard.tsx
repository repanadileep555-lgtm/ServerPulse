interface SessionCardProps {
  username: string
  privileges: string
}

export function SessionCard({ username, privileges }: SessionCardProps) {
  return (
    <article className="card">
      <div className="card-header">
        <h2>Session</h2>
        <span className="badge badge-online">Active</span>
      </div>
      <dl className="meta">
        <div>
          <dt>Signed in as</dt>
          <dd>{username}</dd>
        </div>
        <div>
          <dt>Privileges</dt>
          <dd>{privileges}</dd>
        </div>
        <div>
          <dt>Token</dt>
          <dd>Bearer, refreshed automatically</dd>
        </div>
      </dl>
    </article>
  )
}
