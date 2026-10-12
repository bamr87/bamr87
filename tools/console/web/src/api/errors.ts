// The one error type every backend throws (client.ts, static.ts, ghdirect.ts),
// so a page reads `status` and `message` the same way whoever answered.
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
