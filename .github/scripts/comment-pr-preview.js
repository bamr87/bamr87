#!/usr/bin/env node

// Post preview deployment comment on PR
// Requires: github, context from actions/github-script
// Args: prNumber, triggerStatus, deploymentUrl, deploymentId, projectName, projectUrl

module.exports = async ({github, context, prNumber, triggerStatus, deploymentUrl, deploymentId, projectName, projectUrl}) => {
  const commentHash = `[preview-deployment]: #preview-deployment-${prNumber}`;
  
  // Use environment variables or defaults
  const PROJECT_NAME = projectName || process.env.PROJECT_NAME || 'Project';
  const PROJECT_URL = projectUrl || process.env.PROJECT_URL || deploymentUrl;

  // Delete old preview comments by finding our hash
  const comments = await github.rest.issues.listComments({
    owner: context.repo.owner,
    repo: context.repo.repo,
    issue_number: prNumber
  });

  for (const comment of comments.data) {
    if (comment.user.login === 'github-actions[bot]' && comment.body.includes('[preview-deployment]:')) {
      await github.rest.issues.deleteComment({
        owner: context.repo.owner,
        repo: context.repo.repo,
        comment_id: comment.id
      });
    }
  }

  // Format timestamp like Vercel (UTC)
  const now = new Date();
  const timestamp = now.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: 'UTC'
  });

  let message = '';

  if (triggerStatus === 'success') {
    const previewUrl = deploymentUrl || PROJECT_URL;
    const inspectorUrl = deploymentId ? `${PROJECT_URL}/${deploymentId}` : PROJECT_URL;

    message = `${commentHash}\nDeployment preview from this PR\n\n` +
              `| Project | Deployment | Preview | Updated (UTC) |\n` +
              `| :--- | :----- | :------ | :------ |\n` +
              `| [${PROJECT_NAME}](${inspectorUrl}) | 🤷 Unknown | [Preview](${previewUrl}) | ${timestamp} |\n\n` +
              `*Preview will be ready shortly. Click Preview link above to access the deployment.*`;
  } else {
    message = `${commentHash}\n⚠️ **Preview Build Failed**\n\n` +
              `Preview build could not be triggered. Check the [GitHub Action logs](https://github.com/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}) for details.`;
  }

  await github.rest.issues.createComment({
    issue_number: prNumber,
    owner: context.repo.owner,
    repo: context.repo.repo,
    body: message
  });
};
