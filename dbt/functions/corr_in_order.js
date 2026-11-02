let n = 0, meanX = 0, meanY = 0, coMoment = 0;
let countX = 0, ownMeanX = 0, squaresX = 0;
let countY = 0, ownMeanY = 0, squaresY = 0;
for (const pair of pairs || []) {
  if (pair.y === null || pair.x === null) continue;
  n += 1;
  const dx = pair.x - meanX;
  meanX += dx / n;
  meanY += (pair.y - meanY) / n;
  coMoment += dx * (pair.y - meanY);
  countX += 1;
  const deltaX = pair.x - ownMeanX;
  ownMeanX = ownMeanX + deltaX / countX;
  squaresX += deltaX * (pair.x - ownMeanX);
  countY += 1;
  const deltaY = pair.y - ownMeanY;
  ownMeanY = ownMeanY + deltaY / countY;
  squaresY += deltaY * (pair.y - ownMeanY);
}
if (n === 0) return null;
return (coMoment / n) / (Math.sqrt(squaresX / n) * Math.sqrt(squaresY / n));
