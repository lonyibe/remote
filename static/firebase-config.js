// Import the functions you need from the SDKs you need
import { initializeApp } from "https://www.gstatic.com/firebasejs/9.6.1/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/9.6.1/firebase-auth.js";

// Your web app's Firebase configuration
const firebaseConfig = {
  apiKey: "AIzaSyCSLYVUGJ9to6Cg_WlCma5QctXyEup5-gE",
  authDomain: "storage-9f5d9.firebaseapp.com",
  projectId: "storage-9f5d9",
  storageBucket: "storage-9f5d9.appspot.com",
  messagingSenderId: "478256904589",
  appId: "1:478256904589:web:8275dc9473f17998d765c4",
  measurementId: "G-J86X8GE4LL"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const firebase = { auth: getAuth(app) };
window.firebase = firebase;
