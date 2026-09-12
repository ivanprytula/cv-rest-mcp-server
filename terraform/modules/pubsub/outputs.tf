output "posting_changed_topic_id" {
  description = "Full topic path (projects/<project>/topics/posting-changed) for settings.pubsub_posting_changed_topic."
  value       = google_pubsub_topic.posting_changed.id
}

output "posting_changed_dlq_topic_id" {
  description = "Dead-letter topic path — Phase 3f PR3's push subscription forwards here after its retry policy is exhausted."
  value       = google_pubsub_topic.posting_changed_dlq.id
}
