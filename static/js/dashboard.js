new Chart(document.getElementById("weeklyChart"), {
  type: "bar",
  data: {
    labels: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],
    datasets: [
      { label:"Study Time", data:[2,3,2,4,3.5,5,4], backgroundColor:"#8b5cf6" },
      { label:"Quizzes", data:[1,1.5,1,2,1.5,2.5,2], backgroundColor:"#ec4899" },
      { label:"Games", data:[0.5,1,0.5,1.5,1,2,1.5], backgroundColor:"#f59e0b" }
    ]
  },
  options: {
    responsive:true,
    borderRadius:10,
    scales:{ y:{ beginAtZero:true } }
  }
});
